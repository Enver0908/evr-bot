# 🌟 KMFG EVR Trading Bot - Project Context & Rules

Bu doküman, yapay zeka ajanının projeyi hatasız ve kurumsal standartlarda geliştirmesi için hazırlanmıştır. Ajan, sisteme herhangi bir kod eklerken öncelikle bu dokümandaki ilkelere uymak zorundadır.

## 🏗 İş Mimarisi (Business Logic)
1. **Veri Kaynağı:** KMFG endeksi `kmquant.com/panel/panel.php` üzerinden `evr_scraper.py` vasıtasıyla çekilir.
2. **Cloudflare Bypass:** Scraper; Playwright **KULLANMAZ!** Onun yerine `curl_cffi` (impersonate="chrome110") ve `capsolver` API Kullanarak Turnstile engelini geçer, arkadaki JSON veritabanına doğrudan saldırır.
3. **Strateji ve Durum Makinesi:** Bot, **Spot BTC/USDT** üzerinde çalışan 4 durumlu (NORMAL, SHIELD, BLIND, RESTORE) makro bir swing botudur. Kaldıraç, sabit stop-loss veya take-profit **YOKTUR**.
   - **NORMAL:** Fiyat MA600'ün üzerindeyken EVR kurallarına göre işlem yapılır (EVR <= 3.2 Al, EVR >= 8.5 Sat).
   - **SHIELD:** Fiyat MA600'ün altına düştüğünde eldeki tüm BTC satılır ve nakit moduna geçilir.
   - **Mükerrer İşlem Koruması:** Aynı gün içinde sadece tek başarılı al/sat işlemi gerçekleşir.

## 🧑‍💻 Yazılım Geliştirme Kuralları (Agent Rules)
Ajan, geliştirme yaparken aşağıdaki kurallardan çıkmamalıdır:

1. **Kod Parçalama & Değiştirme:** Yeni bir özellik ekleneceğinde mevcut sistemi bozmadan, geriye dönük uyumluluğu koruyarak eklemeler yap. Dosyayı tamamen silip baştan yazma.
2. **Değişken Adlandırmaları:** Proje genelinde İngilizce değişken ve fonksiyon isimleri (`fetch_data`, `calculate_ma600` vb.) kullanılmalıdır.
3. **Dil Kullanımı:** Kodun içindeki **yorumlar ve açıklama satırları Türkçe** olmalıdır, bu sayede sistem sahibi daha rahat anlayabilir.
4. **Loglama Pratiği:** Hiçbir yerde izole `print()` kullanma. Daima `logging.getLogger("...")` ile sistem loglarına yaz.
5. **Arayüz (UI) Müdahaleleri:** Eski 'highcharts' sorunları çözüldü, frontend'deki çizgiler düzeltildiyse tekrar oraları bozacak eski metotlara başvurma.

Yapay Zeka (*Antigravity*) bu dokümanı her turunu başlattığında baz almalıdır.
