# EVR Trading Bot: Sistem Mimarisi ve Teknik Dokümantasyon

Bu belge, EVR Trading Bot'un (v8 - SQL Refactored sürümü) uçtan uca mimarisini, veri akışını ve strateji durum makinesini (State Machine) açıklamaktadır. Sistem, Bybit üzerinden kripto para alıp satmayı "Duygu (EVR Endeksi)" ve "Trend (MA_600)" kesişimi ile yöneten gelişmiş bir otomatik ticaret platformudur.

---

## 1. Veri Akışı ve Veritabanı Mimarisi (SQL)
Sistem önceden CSV dosyalarına dayanmaktayken, kurumsal dayanıklılık için PostgreSQL/SQLite destekli tam bir ORM (SQLAlchemy) yapısına geçirilmiştir. Tüm veri `evr_bot.db` veya Docker üzerindeki `pgdata` volume'unda saklanır.

### Modeller (`models.py`)
- **User:** Çoklu kullanıcı altyapısı. Her kullanıcının abonelik bilgisi (`SubscriptionStatus`) ve *Şifrelenmiş (Fernet)* Bybit API anahtarları tutulur.
- **UserBotState:** Her kullanıcının bağımsız bot hafızası. Kullanıcının ATH (All-Time High) skoru, Kırılım referansı (Breakdown Price), şu anki pozisyonu (NORMAL, SHIELD, BLIND) güvendedir. Kapanıp açılsa bile durumu buradan okur.
- **TradeLog:** Kesinleşmiş alım/satım (BUY, SELL, SHIELD_SELL) emirlerinin kayıtları.
- **MarketData:** Tarih bazlı Piyasa Belleği. Günlüğün Bybit'teki TSİ 10:00 Kapanış (`btc_price`), Ham Duygu Puanı (`evr_raw`), Endeks (`evr_index`) ve 600 Günlük Hareketli Ortalama (`ma_600`) değerleri. 

### Veri Besleme Sistemi (`daily_updater.py` ve `evr_scraper.py`)
1. **Zaman Mekanizması:** Arka planda 7/24 döngü ile çalışır (`python daily_updater.py --loop`) veya `main_bot.py` üzerinden `APScheduler` ile her sabah tetiklenir.
2. **KMFG Scraper:** Uygulama, veri sağlayıcısına `chromedriver` ve **CapSolver** API'si kullanarak korumaları baypas eder. En son 14 günlük eksik olup olmayan EVR değerleri sisteme çekilir.
3. **Bybit API:** Çekilen EVR tarihlerine karşılık gelen TSİ 10:00 mumu (UTC 07:00 kapanışı) Bybit'ten API ile çekilir.
4. **Upsert (Self-Healing):** Alınan veriler `MarketData` tablosuna güncellenir/yazılır. Eksik MA_600 hesaplamaları geriye dönük veritabanında toplu olarak mühürlenir.

---

## 2. Platform ve Arayüz (FastAPI)
Monolitik uygulama parçalanarak Router/Controller mantığına (`evr_bot/api/` alt klasörü) oturtulmuştur.
- **`app.py`:** Ana entry-point. Uvicorn sunucusunu başlatır, static dosyaları sunar ve CORS/Jinja2 tasarımlarını hazırlar.
- **`api/auth.py`:** Kullanıcı giriş, kayıt ve JWT Session yönetimleri.
- **`api/dashboard.py`:** Sitenin kalbi. 
  - `/api/chart-data`: Veritabanındaki `MarketData` verisini web grafiğine anlık JSON olarak gönderir.
  - `/api/live-status`: Botun o gün MA600/EVR dengesinde ne durumda olduğu bilgisini canlı olarak simüle eder.
- **`api/backtest.py`:** Arayüz üzerinden seçilen herhangi bir iki tarih arasında "Bu parametrelerle işlem yapsam kaç Dolar kâr ederdim ve maksimum zarar (Max Drawdown) ne olurdu?" simülasyonunu anlık çalıştırıp analiz sonucu (Equity Curve dahil) döner.

---

## 3. Ticaret Motoru Stratejisi (State Machine)
Bot 3 aşamalı (Durum Makinesi) bir yapıda çalışır. Tüm bu mantık `evr_bot/trading_engine.py` de hesaplanır. Bot, risk limitlerine (Market order gönderimi, Minimum Order Büyüklüğü vb.) sahiptir.

### STATE 1: [NORMAL] "Trend Modu"
- **Koşul:** BTC Fiyatı > MA_600 (veya ATH seviyelerinde).
- **Aksiyon:** 
  - Eğer EVR <= 5 (Aşırı Korku): Belirlenen `%BUY_PERCENT` (Örn: kasanın %10'u) kadar **ALIM**.
  - Eğer EVR >= 85 (Aşırı Açgözlülük): Belirlenen `%SELL_PERCENT` (Örn: kasanın %20'si) kadar **SATIM**.
- **Durum Değişimi:** Çöküş yaşanır ve Fiyat MA_600'ün altına düşerse -> `SHIELD` moduna geçer ve o günkü fiyattan **ELDEKİ TÜM BTC'YI SATIP (Nakit Güvenliğe) ÇIKAR**. O fiyat "Breakdown Reference" (Kırılım Referansı) olarak hafızaya kazınır.

### STATE 2: [SHIELD] "Kalkan/Bekleyiş Modu"
- **Koşul:** Fiyatın MA_600'ün altında kalması.
- **Aksiyon:** Bu modda EVR ne sinyal verirse versin (dip verse bile) bot alım/satım **YAPMAZ**. Nakitte (USDT) bekler (Sermaye koruması).
- **Durum Değişimi (İyileşme):** Fiyat tekrar toparlar ve MA_600'ün üstüne atarsa -> `NORMAL` moda geri döner, kırılım iptal olur.
- **Durum Değişimi (Kriz Derinleşirse):** Fiyat, Kırılım Referansından belirli bir % daha **DÜŞERSE** (Örn: %40 çöküş) *VEYA* EVR tam endeksi "0.0" olursa pazar pes etmiş (Kan gövdeyi götürüyor) demektir -> `BLIND` moduna geçilir.

### STATE 3: [BLIND] "Zombileşme / Dipten Toplama Modu"
- **Koşul:** Aşırı düşüş veya Pazar ölümü (EVR=0.0). Pazar dibi gelmiştir.
- **Aksiyon:** MA_600 tamamen görmezden gelinir (Blind). Zira ortalamalar artık çöp olmuştur. 
  - EVR 5'in altına (Aşırı Korkuya) her düştüğünde korkmadan Kademeli Maliyetlenme (**ALIM**) yapılır. Satım için yüksek EVR beklenir.
- **Durum Değişimi (Diriliş):** Fiyat, aylar/yıllar sonra tekrar eski Eski ATH (Highest Peak) seviyesine kadar yükseldiğinde -> Vurgun yapılmış sayılır, Pazar iyileşmiştir, bot `NORMAL` moduna döner.

---

## 4. Altyapı ve Güvenlik (DevOps)
- **Gizli Parametreler (`.env`)**: Kriptografik cüzdan anahtarları ve veritabanı şifreleri (`EVR_SECRET_KEY`, `POSTGRES_PASSWORD`). Hardcoded şifre bırakılmamıştır.
- **Uzak Sunucu Hazırlığı (`docker-compose.yml`)**: PostgreSQL Veritabanı (`db`), Gunicorn Web Engine (`web`), Python Cron (`updater`, `bot`) ve Dışarıya Açılmak için Cloudflare Tüneli (`tunnel`) servisleridir. Tümü birbirinin "healthy" (sağlıklı) olmasını bekleyecek şekilde "depends_on" zinciri ile inşa edilmiştir. SQLite (local) ve PostgreSQL (docker) ortamı arasında kayıpsız çalışabilir. 
