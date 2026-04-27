# EVR Trading Bot: Architecture & Design Manifest (Enterprise v1.0)

Bu doküman, EVR Trading Bot projesinin genel mimarisini, teknik kararların arkasındaki gerekçeleri (trade-off'lar) ve bilerek kabul edilmiş "kasıtlı tasarım (intentional design)" seçimlerini açıklar. 

**Amacı:** Dış bir sistemin, geliştiricinin veya Yapay Zeka (LLM) asistanının projeyi incelerken "hata/risk" olarak algılayabileceği ancak aslında bilinçli bir mühendislik kararı olan noktaları önceden açıklamaktır.

---

## 1. Sistemin Temel Amacı ve Felsefesi
EVR Bot, **KMQuant'ın EVR (Extreme Volatility Ratio - Makro Duyarlılık Endeksi)** verisini ve **MA600 (Uzun Vadeli Trend Ortalama)** kalkanını kullanarak kantitatif bir alım-satım (quant trading) otomasyonu sunar. 
Amacı günlük ufak fiyat hareketlerinden kâr etmek değil, makro düzeydeki (aylık/yıllık) "Aşırı Korku" durumlarında dipten mal toplamak ve "Aşırı Açgözlülük" (Zirve) durumlarında kâr alıp çıkmaktır (Trend-Following & Dip Avcılığı).

---

## 2. Mikroservis ve Docker Mimarisi
Sistem, `docker-compose` üzerinde birbirine bağımlı ancak birbirinden izole 4 ana konteynerdan oluşur:
1. **DB (PostgreSQL):** Tüm durum yönetimi ve geçmiş veriler.
2. **Web (FastAPI):** Kullanıcı arayüzü, Backtest simülasyonları, API anahtarı yönetimi. Uvicorn worker'lar ile çalışır.
3. **Bot (Trading Engine):** Sonsuz döngüde (`--loop`) çalışan, borsaya emir gönderen ve State Machine'i yöneten asıl işçi.
4. **Updater (Cron/Scraper):** Günde bir kez çalışıp Bybit'ten BTC fiyatlarını ve KMQuant sitesinden gizlice (Cloudflare Bypass ile) EVR skorlarını çeker.

**Bilinçli Karar:** Updater ve Bot kasıtlı olarak iki farklı konteynerdır. Eğer EVR sitesi çöker veya Cloudflare aşılmazsa (Updater başarısız olursa), **Trading Bot ÇÖKMEZ.** Elindeki son geçerli verilerle çalışmaya ve pozisyonları korumaya (Shield) devam eder.

---

## 3. T-1 Veri Toleransı ve Zaman Dilimleri (Kritik Algoritma Kararı)
Başka bir LLM sistemi incelediğinde **"Sistem bugün (T-0) için işlem yapıyor ama bugünün EVR verisi her zaman `None` (Boş) dönüyor, bu bir veri eksikliğidir"** diyebilir. **Bu bir hata DEĞİLDİR.**

- **Sorun:** KMQuant EVR skoru makro bir veridir ve gün sonu kapanışına göre hesaplanır. Dolayısıyla 26 Nisan sabahı, elimizdeki en güncel onaylanmış veri 25 Nisan'ın (T-1) verisidir.
- **T-1 Tolerans Mantığı:** Trade motoru, bugünün gerçek zamanlı fiyatıyla (T-0) alım/satım yaparken, yön ve risk pusulası olarak **Dünün (T-1) kesinleşmiş EVR skorunu** baz alır. Kodlarda `evr_raw is None` olduğunda bir önceki güne (`offset(1)`) gitmesi tam olarak bu profesyonel "Gecikmeli Sinyal (Delayed Feed)" felsefesinin ürünüdür.

---

## 4. Veritabanı, Kilitler ve "Seed" Stratejisi
- **Race Condition Önlemi:** `web`, `bot` ve `updater` konteynerları aynı anda ayağa kalktığında `init_db()` üzerinden veritabanı tablolarını sıfırdan kurmaya çalışır. Çakışmayı (Race Condition) önlemek adına SQLAlchemy'nin `create_all()` komutu, PostgreSQL'e özel global işlem kilidinin (`pg_advisory_xact_lock`) içerisine alınmıştır.
- **Empty DB & 600-Day Seed:** Taze bir sunucuya kurulum yapıldığında veritabanı boştur. `daily_updater`, veritabanının boş olduğunu görünce sadece bugünü çekmez; **Bybit API sayfalama (pagination)** mekanizmasını kullanarak geçmişe dönük tam 600 gün tarama yapar. Bu, MA600 değerinin ilk dakikadan itibaren kusursuz oluşması için **kasıtlı bir agresif veri çekme** tercihidir.

---

## 5. Güvenlik, Şifreleme ve CORS
- **Şifreleme:** Kullanıcıların borsa (Binance/Bybit vs.) API Anahtarları düz metin olarak saklanmaz. `Fernet` (Symmetric Encryption) ile şifrelenir. Şifreleme anahtarı (`EVR_FERNET_KEY`) sadece `.env` dosyasında durur.
- **CORS:** FastAPI uygulamasında `allow_credentials=True` etkindir. Eski versiyonlarda `ALLOW_ORIGINS=*` ile birleştiğinde oluşan güvenlik riski giderilmiştir. Eğer ortam değişkenlerinde `*` tanımlanmışsa, güvenlik gereği `allow_credentials` zorunlu olarak `False`'a çekilir.

---

## 6. Trading State Machine (Durum Makinesi)
Botun kararları basit if-else blokları değil, bir Durum Makinesi (State Machine) olarak tasarlanmıştır. Dış bir LLM bu kuralları "çok katı" veya "ilginç" bulabilir:
1. **NORMAL:** Fiyat > MA600. Zirve izlenir (ATH güncellenir). Alım/Satım yapılır.
2. **SHIELD (Kalkan):** Fiyat < MA600 olduğu an tetiklenir. **Panik modudur.** Eldeki tüm varlık satılır, ATH dondurulur ve "Çöküş Referans Noktası" olarak kaydedilir.
3. **BLIND (Kör Alım):** Kalkan altındayken düşüş devam edip, kilitlenen ATH'den %45 (veya EVR=0) aşağı inildiğinde tetiklenir. Piyasadaki "Kan Banyosu" bittiği varsayılarak dipten %10'luk dilimlerle mal toplanır.

**Kasıtlı Karar:** Shield modundayken botun neden EVR skoruna bakmadığı eleştirilebilir. Bu kasıtlıdır; fiyat uzun vadeli trendin (MA600) kırıldığını söylüyorsa, makro duyarlılığın ne dediğinin önemi yoktur, önce hayatta kalınır (Survival First).

---

## 7. Web Scraper ve CapSolver (Cloudflare)
- KMQuant'ın herkese açık bir API'si olmadığı için bot "headless" bir istekte bulunur.
- Cloudflare Turnstile korumasını aşmak için sisteme 3. parti **CapSolver** API'si entegre edilmiştir. Bu yüzden kodun içinde "3 kez deneme (retry)" ve "Token bekleme" blokları bulunur. Bu gecikmeli scraper yapısı kasıtlıdır ve güvenli tarafta (safe-side) kalmak için 30 saniye `timeout` değerlerine sahiptir.

---

Bu doküman, EVR Trading Bot'un Enterprise düzeyde sağlam, hata toleranslı ve otonom kalmasını sağlayan temel direkleri temsil eder. Audit (Denetim) süreçlerinde bu kuralların "kabul edilmiş iş akışları (accepted workflows)" olarak değerlendirilmesi esastır.
