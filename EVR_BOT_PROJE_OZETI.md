# EVR Trading Bot — Proje Özeti ve Mevcut Durum
**Tarih:** 22 Nisan 2026 | **Versiyon:** Enterprise v1.0 (Production-Ready)

---

## 📌 PROJE NEDİR?

**EVR Trading Bot**, birden fazla kullanıcı için çalışan, abonelik tabanlı, otomatik bir BTC/USDT alım-satım botudur.

### Temel Strateji
- **EVR (KMQuant KMFG Endeksi)** değerine göre alım-satım kararı alır.
  - `EVR <= 3.2` → BTC AL (%2 kasadan)
  - `EVR >= 8.5` → BTC SAT (%15 pozisyondan)
- **MA600 (600 Günlük Hareketli Ortalama)** fiyat kırılım koruması:
  - Fiyat < MA600 → **SHIELD** modu: Tüm BTC sat, nakit bekle
  - Fiyat >= MA600 → **NORMAL** moda dön
- **BLIND** modu: SHIELD'deyken EVR = 0 olursa (dip görüldü) alıma hazır

### Durum Makinesi
| Durum | Anlamı |
|-------|--------|
| `NORMAL (1)` | Fiyat > MA600, EVR kuralları aktif |
| `SHIELD (2)` | Fiyat < MA600, nakit modda bekle |
| `BLIND (3)` | Dip bölgesi, alım fırsatı |

---

## 🏗️ MİMARİ

### Teknoloji Yığını
- **Backend:** Python, FastAPI, SQLAlchemy (ORM)
- **Veritabanı:** SQLite (dev) / PostgreSQL (prod)
- **Borsa:** Bybit (ccxt kütüphanesi üzerinden)
- **Zamanlayıcı:** APScheduler (BlockingScheduler)
- **Container:** Docker + docker-compose
- **Veri Kaynağı:** KMQuant (EVR), Bybit (BTC fiyatı)
- **CAPTCHA Bypass:** CapSolver (Turnstile)

### Klasör Yapısı
```
ai ajan/
├── evr_bot/
│   ├── app.py              # FastAPI ana uygulama
│   ├── config.py           # Tüm sabitler ve ayarlar
│   ├── models.py           # SQLAlchemy modelleri
│   ├── database.py         # DB bağlantı yönetimi
│   ├── market_data.py      # Bybit API, MA600, referans fiyat
│   ├── trading_engine.py   # Ana trade motoru (state machine)
│   ├── evr_data.py         # EVR endeks okuyucu
│   ├── main_bot.py         # Scheduler ve job tanımları
│   ├── crypto_utils.py     # Fernet şifreleme (API key güvenliği)
│   └── api/
│       ├── auth.py         # Login/register endpointleri
│       ├── dashboard.py    # Dashboard ve canlı veri
│       ├── keys.py         # Bybit API key yönetimi
│       ├── backtest.py     # Strateji simülatörü
│       ├── deps.py         # JWT yetkilendirme bağımlılıkları
│       └── schemas.py      # Pydantic şemaları
├── evr_scraper.py          # KMQuant web scraper (CapSolver)
├── daily_updater.py        # Günlük veri çekici (BTC + EVR)
├── run.py                  # Başlatıcı (api/bot/all)
├── docker-compose.yml
└── Dockerfile
```

---

## ⏰ ZAMANLAMA (SCHEDULER)

```
07:15 UTC → daily_updater: Bybit BTC fiyatı + KMQuant EVR çek → DB'ye yaz
07:25 UTC → Shield Check:  DB'den referans fiyat + MA600 oku → Shield kararı
07:45 UTC → EVR Cycle:     DB'den EVR oku → Alım/satım kararı
```

**Güvenlik:** Her job'da `max_instances=1` kilidi var (aynı iş üst üste çalışmaz).

---

## 🔒 GÜVENLİK MİMARİSİ

### Şifreleme
- Kullanıcı API anahtarları **Fernet** ile şifreli saklanıyor (`EVR_FERNET_KEY`)
- JWT token ile kimlik doğrulama (`EVR_SECRET_KEY`)
- `.env` ve `.fernet_key` → `.gitignore`'da, repoya commit edilmiyor

### Abonelik Kontrolü
- `deps.py → get_current_user()` her API isteğinde subscription kontrolü yapar
- `SubscriptionStatus.ACTIVE` olmayan kullanıcı → `403 Forbidden`

### CORS ve Swagger
- Production ortamında Swagger UI (`/docs`) kapalı (`ENVIRONMENT=production`)
- CORS varsayılanı boş (`""`) — sadece `ALLOWED_ORIGINS` env ile açılır

---

## 🗄️ VERİTABANI MODELLERİ

### User
- `id`, `email`, `hashed_password`
- `subscription_status` (ACTIVE/INACTIVE/EXPIRED)
- `subscription_expires_at`

### UserBotState
- `user_id` (FK)
- `current_state` (BotStateEnum: NORMAL/SHIELD/BLIND)
- `last_btc_price`, `last_ma600`
- `eski_zirve_fiyati` (ATH takibi)
- `breakdown_reference_price` (SHIELD giriş fiyatı)

### TradeLog
- `user_id`, `action` (BUY/SELL/SHIELD_SELL/STATE_CHANGE)
- `execution_status` (**PENDING/FILLED/FAILED/UNKNOWN** — Outbox pattern)
- `symbol`, `side`, `amount_btc`, `amount_usdt`, `price`, `order_id`
- `evr_value`, `bot_state_at`, `note`

### MarketData
- `date_str` (PRIMARY KEY: YYYY-MM-DD)
- `btc_price` (07:00 UTC referans fiyatı — GÜNLÜK KAPANIŞ DEĞİL!)
- `ma_600` (önceden hesaplanmış, performans için)
- `evr_value`

---

## ✅ TAMAMLANAN ÖNEMLİ YAMALAR

### Patch 1-2 (Mimari Refaktör)
- [x] Tüm veri akışı CSV'den SQL'e taşındı (Single Source of Truth)
- [x] Kullanıcı başına izole DB session (Transaction Poisoning önlendi)
- [x] EVR fallback (dünkü veri kullanma) kaldırıldı — strict freshness politikası

### Patch 3 (Enterprise Mimari)
- [x] **Outbox Pattern:** `PENDING → FILLED/FAILED` atomik emir akışı
- [x] **Shield Atomic State:** Kalkan satışı ve SHIELD moduna geçiş tek commit'te
- [x] **Session İzolasyonu:** `db.merge()` → `db.query(User).get(uid)` (fresh query)
- [x] **Terminoloji:** `get_last_daily_close_from_db` → `get_reference_price_from_db`
- [x] **Zamanlama:** 00:05 UTC → 07:25 UTC (updater ile senkronize)
- [x] **max_instances=1** tüm job'lara eklendi
- [x] **Docker Healthcheck:** 480dk → 1560dk (26 saat)
- [x] **Scraper timeout:** Tüm HTTP isteklerine `timeout=30` eklendi

### Patch 4 (Güvenlik ve API)
- [x] **JWT Abonelik Kontrolü:** `deps.py`'de `SubscriptionStatus.ACTIVE` zorunlu
- [x] **Swagger Gizleme:** Production'da `/docs` ve `/redoc` kapalı
- [x] **CORS:** Varsayılan `*` → `""` (kapalı)
- [x] **Key Rotation:** `EVR_SECRET_KEY` yeni güvenli anahtarla değiştirildi
- [x] **`.fernet_key` silindi** (env variable üzerinden çalışıyor)
- [x] **MA600 None koruması:** `btc_price is not None` + `float()` dönüşümü

---

## ⚠️ BİLİNEN / AÇIK KONULAR (Yapılmadı)

1. **`/api/live-status` endpoint'i** → Her istekte tüm geçmişi iterate ederek state hesaplıyor. Bu endpoint, botun gerçek DB state'ini değil, matematiksel piyasa durumunu gösteriyor. **Kasıtlı mimari karar** (multi-user platform olduğu için kişisel bot state'i değil global piyasa durumu gösteriliyor).
2. **PENDING Trade Recovery** → Eğer `db.commit()` başarısız olursa borsa emri gerçekleşmiş ama DB'de PENDING kalır. Monitoring/alert sistemi henüz yok.
3. **Alembic Migration** → Şema yönetimi hala `create_all()` ile. İleride Alembic migration planlanmalı.
4. **Backtest MA600 tutarsızlığı** → Backtest kendi MA600'ünü hesaplıyor, trading engine DB değerini kullanıyor. Kasıtlı sandbox tasarımı, şimdilik sorun değil.
5. **JWT süresi** → 24 saat. Finans uygulaması için 8 saat daha güvenli (opsiyonel).

---

## 🚀 CANLIYA ÇIKIŞ

```bash
# Eski container'ları durdur
docker-compose down

# Yeni image'ı build et ve başlat
docker-compose up -d --build

# Log takibi
docker-compose logs -f bot
docker-compose logs -f api
```

### Zorunlu .env Değişkenleri
```
EVR_SECRET_KEY=<güvenli rastgele hex>
EVR_FERNET_KEY=<Fernet.generate_key() çıktısı>
POSTGRES_PASSWORD=<güçlü şifre>
KMFG_EMAIL=<kmquant email>
KMFG_PASSWORD=<kmquant şifre>
CAPSOLVER_KEY=<capsolver api key>
ALLOWED_ORIGINS=https://sitenindomaini.com
ENVIRONMENT=production
```

---

## 🧪 TEST / DOĞRULAMA

```bash
# Syntax kontrolü
python -m py_compile evr_bot/trading_engine.py evr_bot/main_bot.py evr_bot/market_data.py evr_bot/models.py

# API sunucusu başlatma (dev)
python run.py api

# Kullanıcı aboneliği aktif etme
python -c "
from evr_bot.database import SessionLocal
from evr_bot.models import User, SubscriptionStatus
from datetime import datetime, timezone, timedelta
db = SessionLocal()
user = db.query(User).filter(User.email == 'EMAIL@ADRESIN.COM').first()
user.subscription_status = SubscriptionStatus.ACTIVE
user.subscription_expires_at = datetime.now(timezone.utc) + timedelta(days=365)
db.commit()
db.close()
print('Abonelik aktif edildi.')
"
```

---

## 📊 ÖNEMLİ DEĞERLER (config.py)

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| `MA_PERIOD` | 600 | 600 günlük hareketli ortalama |
| `EVR_BUY_THRESHOLD` | 3.2 | EVR <= 3.2 → AL |
| `EVR_SELL_THRESHOLD` | 8.5 | EVR >= 8.5 → SAT |
| `BUY_PERCENT` | 0.02 | Kasa'nın %2'si |
| `SELL_PERCENT` | 0.15 | BTC'nin %15'i |
| `BREAKDOWN_DROP_PERCENT` | 0.45 | %45 düşüş → BLIND |
| `MIN_ORDER_USDT` | 5.0 | Bybit minimum |

---

> **Not:** Bu belge, EVR Trading Bot projesinin tüm mimarisi, tamamlanan yamalar ve mevcut durumu hakkında kapsamlı bir özettir. Yeni bir AI oturumunda bu belgeyi paylaşarak kaldığınız yerden devam edebilirsiniz.
