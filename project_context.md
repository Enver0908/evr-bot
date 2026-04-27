# 🌟 KMFG EVR Trading Bot - Project Context & Rules

Bu doküman, yapay zeka ajanının projeyi hatasız ve kurumsal standartlarda geliştirmesi için hazırlanmıştır. Ajan, sisteme herhangi bir kod eklerken öncelikle bu dokümandaki ilkelere uymak zorundadır.

## 🏗 İş Mimarisi (Business Logic)
1. **Veri Kaynağı:** KMFG endeksi `kmquant.com/panel/panel.php` üzerinden `evr_scraper.py` vasıtasıyla çekilir.
2. **Cloudflare Bypass:** Scraper; Playwright **KULLANMAZ!** Onun yerine `curl_cffi` (impersonate="chrome110") ve `capsolver` API Kullanarak Turnstile engelini geçer, arkadaki JSON veritabanına doğrudan saldırır.
3. **DailyGuard Mekanizması:** En kritik risk kontrol kalkanıdır.
   - **Kaldıraç Sınırı:** Maksimum 3x.
   - **Limitler:** %1.5 Stop Loss, %3.0 Take Profit zorunludur.
   - **Günlük Zarar Kes:** Üst üste 3 işlem Stop ile sonuçlanırsa, bot gün bitene kadar yeni işlem açmaz (Drawdown koruması).

## 🧑‍💻 Yazılım Geliştirme Kuralları (Agent Rules)
Ajan, geliştirme yaparken aşağıdaki kurallardan çıkmamalıdır:

1. **Kod Parçalama & Değiştirme:** Yeni bir özellik ekleneceğinde mevcut sistemi bozmadan, geriye dönük uyumluluğu koruyarak eklemeler yap. Dosyayı tamamen silip baştan yazma.
2. **Değişken Adlandırmaları:** Proje genelinde İngilizce değişken ve fonksiyon isimleri (`fetch_data`, `calculate_ma600` vb.) kullanılmalıdır.
3. **Dil Kullanımı:** Kodun içindeki **yorumlar ve açıklama satırları Türkçe** olmalıdır, bu sayede sistem sahibi daha rahat anlayabilir.
4. **Loglama Pratiği:** Hiçbir yerde izole `print()` kullanma. Daima `logging.getLogger("...")` ile sistem loglarına yaz.
5. **Arayüz (UI) Müdahaleleri:** Eski 'highcharts' sorunları çözüldü, frontend'deki çizgiler düzeltildiyse tekrar oraları bozacak eski metotlara başvurma.

Yapay Zeka (*Antigravity*) bu dokümanı her turunu başlattığında baz almalıdır.
