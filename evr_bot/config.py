"""
EVR Trading Bot — Konfigürasyon
================================
Tüm sabitler, eşik değerleri ve ortam ayarları.
Ortam değişkenleri .env dosyasından veya sistem env'den okunur.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Docker ortamında dotenv gerekmez

# ─── Dizin Yolları ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Veritabanı ──────────────────────────────────────────────────────────────
# Ortam degiskeninde DATABASE_URL varsa onu kullan (PostgreSQL veya baska).
# Yoksa SQLite ile calis (gelistirme ortami icin).
_DB_PATH = BASE_DIR / "evr_bot.db"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{_DB_PATH}",
)

# ─── Güvenlik ─────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("EVR_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("KRİTİK HATA: .env dosyasında EVR_SECRET_KEY tanımlı değil! Lütfen geçerli bir şifre belirleyin.")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24  # 24 saat

# ─── Bybit (Testnet) ─────────────────────────────────────────────────────────
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
EXCHANGE_ID = "bybit"
SYMBOL = "BTC/USDT"

# ─── Strateji Parametreleri ──────────────────────────────────────────────────
MA_PERIOD = 600                    # 600 günlük hareketli ortalama
EVR_BUY_THRESHOLD = 3.2           # EVR <= 3.2 → AL
EVR_SELL_THRESHOLD = 8.5          # EVR >= 8.5 → SAT
BUY_PERCENT = 0.02                # Kasa'nın %2'si ile al
SELL_PERCENT = 0.15               # BTC'nin %15'ini sat
BREAKDOWN_DROP_PERCENT = 0.45     # %45 düşüş eşiği
MIN_ORDER_USDT = 5.0              # Bybit minimum order

# ─── Durum Makinesi Sabitleri ────────────────────────────────────────────────
STATE_NORMAL = 1    # Fiyat > MA_600, EVR kuralları aktif
STATE_SHIELD = 2    # Fiyat < MA_600, nakit modda bekle
STATE_BLIND = 3     # Dip bölgesi, MA_600 devre dışı

# ─── Zamanlayıcı (Scheduler) ─────────────────────────────────────────────────
SHIELD_CHECK_UTC_HOUR = 7         # UTC 07:25 (Referans Fiyat Güncellemesinden Sonra)
SHIELD_CHECK_UTC_MINUTE = 25       
EVR_CYCLE_UTC_HOUR = 7            # UTC 07:45 (TSİ 10:45)
EVR_CYCLE_UTC_MINUTE = 45



# ─── Loglama ─────────────────────────────────────────────────────────────────
LOG_FILE = BASE_DIR / "evr_bot.log"
