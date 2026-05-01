"""
EVR Daily Data Updater (SQL MİMARİSİ)
====================================================
Bybit'ten günlük kapanışları (MA600) ve kmquant'tan EVR 
verilerini çekerek doğrudan MarketData SQL tablosuna yazar.

Kullanım:
    python daily_updater.py           # Tek sefer
    python daily_updater.py --loop    # 24 saat döngüde
"""
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Ortam değişkenlerini yükle (TÜM importlardan ÖNCE çağrılmalıdır) ──
# evr_scraper modülü import anında KMFG_EMAIL, KMFG_PASSWORD, CAPSOLVER_KEY
# değişkenlerini os.environ'dan okur. load_dotenv() daha sonra çağrılırsa
# bu değerler None kalır ve scraper sessizce başarısız olur.
from dotenv import load_dotenv
load_dotenv()

from evr_scraper import scrape
from evr_bot.database import SessionLocal, init_db
from evr_bot.models import MarketData
from evr_bot.config import MA_PERIOD

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

# ═══════════════════════════════════════════════════════════════════════════════
# YAPILANDIRMA
# ═══════════════════════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "daily_updater.log"

SELF_HEALING_DAYS = 30

# RotatingFileHandler: max 10MB, 5 yedek dosya
_rotating_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_rotating_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        _rotating_handler,
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daily_updater")


# ─── Docker Healthcheck Heartbeat ────────────────────────────────────────────
def _write_heartbeat() -> None:
    """Docker healthcheck için heartbeat dosyasını günceller (touch)."""
    try:
        data_dir = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "updater_heartbeat").touch()
    except Exception as exc:
        logger.warning("Heartbeat yazılamadı: %s", exc)


# ─── DB Startup Dayanıklılığı ────────────────────────────────────────────────
def _wait_for_db(max_retries: int = 10) -> None:
    """
    PostgreSQL hazır olana kadar exponential backoff ile bekle.
    Tüm denemeler başarısız olursa process non-zero çıkar;
    Docker restart: always ile yeniden başlatılır.
    """
    from sqlalchemy import text as sa_text
    from evr_bot.database import SessionLocal

    for attempt in range(1, max_retries + 1):
        db = None
        try:
            db = SessionLocal()
            db.execute(sa_text("SELECT 1"))
            db.close()
            logger.info("DB bağlantısı başarılı (deneme %d/%d).", attempt, max_retries)
            return
        except Exception as e:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass
            wait = min(5 * (2 ** (attempt - 1)), 60)  # 5s, 10s, 20s, 40s, 60s...
            logger.warning(
                "DB henüz hazır değil (deneme %d/%d): %s — %ds bekleniyor...",
                attempt, max_retries, str(e)[:100], wait,
            )
            time.sleep(wait)

    logger.critical(
        "DB RETRY LİMİTİ AŞILDI (%d deneme). Process sonlandırılıyor. "
        "Docker restart: always ile yeniden başlatılacak.",
        max_retries,
    )
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_btc_price_10am() -> float | None:
    """
    Bybit Spot API'den bugünün 07:00 UTC
    saatlik mumunun Open fiyatını çeker.
    """
    if curl_requests is None:
        logger.error("curl_cffi yüklü değil, Bybit'e bağlanılamıyor.")
        return None

    try:
        url = "https://api.bytick.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=60&limit=24"
        resp = curl_requests.get(url, impersonate="chrome110", timeout=15)
        data = resp.json().get("result", {}).get("list", [])
        if not data:
            logger.error("Bybit kline verisi boş döndü.")
            return None

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for candle in data:
            ts = int(candle[0])
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            if dt.hour == 7:
                candle_date = dt.strftime("%Y-%m-%d")
                if candle_date == today_str:
                    price = round(float(candle[1]), 2)
                    logger.info("10:00 TSİ (07:00 UTC) BTC fiyatı: $%.2f (%s)", price, candle_date)
                    return price

        logger.warning("Bugünün (%s) 07:00 UTC mumu bulunamadı.", today_str)
        return None
    except Exception as e:
        logger.error("BTC 10:00 fiyat çekilemedi: %s", e)
        return None


def fetch_btc_prices_for_dates(date_strs: list[str]) -> dict[str, float]:
    """Birden fazla tarih için Bybit'ten 07:00 UTC (10:00 TSİ) fiyatlarını çeker."""
    if not date_strs:
        return {}

    if curl_requests is None:
        logger.error("curl_cffi yüklü değil, tarihsel Bybit verisi çekilemiyor.")
        return {}

    prices = {}
    try:
        sorted_dates = sorted(date_strs)
        oldest = sorted_dates[0]
        
        oldest_dt = datetime.strptime(oldest, "%Y-%m-%d").replace(
            hour=0, minute=0, tzinfo=timezone.utc
        )
        start_ms = int(oldest_dt.timestamp() * 1000)
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        target_dates = set(date_strs)

        # Bybit v5 kline API: veriyi DESC sirali doner (yeniden eskiye).
        # "end" parametresi ile geriye dogru pagination yapilir.
        cursor_end_ms = end_ms
        found_all = False

        while cursor_end_ms > start_ms and not found_all:
            url = (
                f"https://api.bytick.com/v5/market/kline"
                f"?category=spot&symbol=BTCUSDT&interval=60"
                f"&start={start_ms}&end={cursor_end_ms}&limit=1000"
            )
            resp = curl_requests.get(url, impersonate="chrome110", timeout=20)
            data = resp.json().get("result", {}).get("list", [])
            
            if not data:
                break
                
            for candle in data:
                ts = int(candle[0])
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                if dt.hour == 7:
                    d = dt.strftime("%Y-%m-%d")
                    if d in target_dates:
                        prices[d] = round(float(candle[1]), 2)
            
            # Tum hedef tarihler bulunduysa erken cik
            if target_dates.issubset(prices.keys()):
                found_all = True
                break

            # DESC sirali: en eski mum listenin sonunda. Onun timestamp'inden geriye git.
            min_ts = min(int(c[0]) for c in data)
            new_end = min_ts - 1  # 1 ms geri, overlap onlenir

            if new_end >= cursor_end_ms:
                break  # Ilerleme durdu (guvenlik)
            cursor_end_ms = new_end

        logger.info(
            "Bybit'ten %d/%d gün için 10:00 TSİ fiyatları çekildi.",
            len(prices), len(date_strs),
        )
        
    except Exception as e:
        logger.error("Tarihsel BTC fiyat çekme hatası: %s", e)
    
    return prices


# ═══════════════════════════════════════════════════════════════════════════════
# ANA GÜNCELLEME (SQL TABANLI)
# ═══════════════════════════════════════════════════════════════════════════════

def update():
    logger.info("=" * 60)
    logger.info("SQL Güncelleme başlıyor... (%s UTC)", datetime.now(timezone.utc).isoformat())

    _wait_for_db()
    init_db()
    db = SessionLocal()

    try:
        # ═══════════════════════════════════════════════════════════════════
        # ADIM 1: EVR Verisi Çekimi (Bağımsız — başarısızlık BTC'yi engellemez)
        # ═══════════════════════════════════════════════════════════════════
        evr_records = []
        try:
            logger.info("kmquant'tan son %d günün EVR verisi çekiliyor...", SELF_HEALING_DAYS)
            evr_records = scrape(headless=True, last_n_days=SELF_HEALING_DAYS) or []
            if evr_records:
                logger.info("kmquant'tan %d günlük EVR verisi alındı.", len(evr_records))
            else:
                logger.warning(
                    "kmquant'tan EVR verisi alınamadı. "
                    "BTC fiyat güncellemesi bağımsız olarak devam edecek."
                )
        except Exception as evr_exc:
            logger.error(
                "EVR scraper hatası: %s — BTC fiyat güncellemesi bağımsız olarak devam edecek.",
                evr_exc,
            )

        # ═══════════════════════════════════════════════════════════════════
        # ADIM 2: Hedef Tarihleri Belirle (Boşlukları Backfill Et)
        # ═══════════════════════════════════════════════════════════════════
        target_dates = set()
        today_date = datetime.now(timezone.utc).date()
        today_str = today_date.strftime("%Y-%m-%d")

        # Tüm mevcut tarihleri alıp genel boşluk taraması (Universal Gap Scan) yap
        all_db_records = db.query(MarketData.date_str).all()
        existing_dates = {r[0] for r in all_db_records if r[0]}

        if existing_dates:
            min_date_str = min(existing_dates)
            min_date = datetime.strptime(min_date_str, "%Y-%m-%d").date()
            curr_date = min_date
            while curr_date <= today_date:
                d_str = curr_date.strftime("%Y-%m-%d")
                if d_str not in existing_dates:
                    target_dates.add(d_str)
                curr_date += timedelta(days=1)
        else:
            # Taze Kurulum Seed (Empty DB): Ilk gunden 600 gunluk MA_600 icin tam 600 gun cek
            seed_start_date = today_date - timedelta(days=600)
            curr_date = seed_start_date
            while curr_date <= today_date:
                target_dates.add(curr_date.strftime("%Y-%m-%d"))
                curr_date += timedelta(days=1)

        if evr_records:
            for rec in evr_records:
                target_dates.add(rec["date"])

        # EVR Backfill: Mevcut ama EVR'si NULL olan satırları da hedefle (Sadece son 30 gün)
        # NOT: Tüm geçmişin baştan taranmasını (universal scan) önlemek için stale_cutoff (30 gün) sınırı kesin olarak uygulanır.
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=SELF_HEALING_DAYS)).strftime("%Y-%m-%d")
        null_evr_rows = db.query(MarketData.date_str).filter(
            MarketData.evr_raw.is_(None),
            MarketData.date_str >= stale_cutoff
        ).all()
        for row in null_evr_rows:
            target_dates.add(row[0])
        if null_evr_rows:
            logger.info("EVR backfill: %d adet evr_raw=NULL satır hedeflendi.", len(null_evr_rows))

        target_dates.add(today_str)
        target_dates_list = sorted(list(target_dates))

        # Tarihler icin BTC Fiyati Cek
        logger.info(f"{len(target_dates_list)} gün için BTC fiyatları çekiliyor (Backfill/Güncel)...")
        btc_prices = fetch_btc_prices_for_dates(target_dates_list)
        
        # Bugünün fiyatı API'den çekilemediyse fallback 10AM
        if today_str not in btc_prices or btc_prices[today_str] <= 0:
            today_price = fetch_btc_price_10am()
            if today_price:
                btc_prices[today_str] = today_price

        # ═══════════════════════════════════════════════════════════════════
        # ADIM 3 & 4: Veritabanına Yaz
        # ═══════════════════════════════════════════════════════════════════
        evr_dict = {rec["date"]: rec["evr_value"] for rec in evr_records}
        
        for d in target_dates_list:
            evr_val = evr_dict.get(d)
            btc_price = btc_prices.get(d)
            
            market_row = db.query(MarketData).filter(MarketData.date_str == d).first()
            if market_row:
                if evr_val is not None:
                    market_row.evr_raw = evr_val
                    market_row.evr_index = round(evr_val / 10.0, 1)
                if btc_price:
                    market_row.btc_price = btc_price
                logger.info(f"DB Güncellendi: {d} -> BTC=${market_row.btc_price:.2f} EVR={market_row.evr_raw}")
            else:
                if not btc_price:
                    logger.warning(f"{d} için BTC fiyatı bulunamadı, atlanıyor.")
                    continue
                    
                new_row = MarketData(
                    date_str=d,
                    btc_price=btc_price,
                    evr_raw=evr_val,
                    evr_index=round(evr_val / 10.0, 1) if evr_val is not None else None,
                    ma_600=None
                )
                db.add(new_row)
                logger.info(f"DB Yeni Kayıt (Backfill/Güncel): {d} -> BTC=${btc_price:.2f} EVR={evr_val if evr_val is not None else 'N/A'}")

        db.flush()

        # ═══════════════════════════════════════════════════════════════════
        # ADIM 5: MA600 Yeniden Hesaplama
        # ═══════════════════════════════════════════════════════════════════
        all_records = db.query(MarketData).order_by(MarketData.date_str.asc()).all()
        prices_array = [r.btc_price for r in all_records]
        
        needs_commit = False
        for i, record in enumerate(all_records):
            if i >= MA_PERIOD - 1:
                window = prices_array[i - MA_PERIOD + 1 : i + 1]
                new_ma_600 = round(sum(window) / len(window), 2)
                if record.ma_600 != new_ma_600:
                    record.ma_600 = new_ma_600
                    needs_commit = True

        if needs_commit:
            logger.info("Eksik MA600 değerleri veritabanında hesaplandı.")

        # ─── Görünürlük: Bugünün EVR durumunu raporla ────────────────────
        today_row = db.query(MarketData).filter(MarketData.date_str == today_str).first()
        if today_row and today_row.evr_raw is None:
            logger.warning(
                "BUGÜN (%s) EVR VERİSİ HÂLÂ PENDING (evr_raw=NULL). "
                "KMQuant henüz yayınlamamış olabilir. Sonraki backfill koşusunda tekrar denenecek.",
                today_str,
            )

        # 24 saatten eski NULL EVR uyarısı
        # 24 saatten eski NULL EVR uyarısı (Sadece son 30 gün içinde)
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=SELF_HEALING_DAYS)).strftime("%Y-%m-%d")
        stale_nulls = db.query(MarketData).filter(
            MarketData.evr_raw.is_(None),
            MarketData.date_str < stale_cutoff,
            MarketData.date_str >= thirty_days_ago,
        ).count()
        if stale_nulls > 0:
            logger.critical(
                "%d adet 24 saatten eski evr_raw=NULL kayıt var! "
                "KMQuant erişim sorunu olabilir. Manuel kontrol gerekli.",
                stale_nulls,
            )

        db.commit()
        logger.info("SQL Güncelleme tamamlandı.")
        _write_heartbeat()
    except Exception as e:
        db.rollback()
        logger.exception(f"Veritabanı kayıt sırasında hata: {e}")
    finally:
        db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="APScheduler ile sabit saatte çalıştır")
    args = parser.parse_args()

    if args.loop:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger

        logger.info("APScheduler modu başlatılıyor...")
        _write_heartbeat()  # İlk açılışta Docker healthcheck'in unhealthy kalmaması için

        # İlk açılışta hemen bir kez güncelle
        try:
            update()
        except Exception:
            logger.exception("İlk güncelleme hatası")

        scheduler = BlockingScheduler(timezone="UTC")

        # Ana koşu: Her gün UTC 07:15 (TSİ 10:15)
        scheduler.add_job(
            update,
            CronTrigger(hour=7, minute=15),
            misfire_grace_time=3600,
            id="daily_update",
            name="Günlük EVR+BTC Veri Güncellemesi",
        )

        # Telafi koşuları: Aynı gün içinde EVR backfill için ek saatler
        # update() zaten idempotent — var olan satırı günceller, duplicate oluşturmaz
        for job_id, hour, minute in [
            ("backfill_1", 10, 30),   # UTC 10:30 (TSİ 13:30)
            ("backfill_2", 14, 0),    # UTC 14:00 (TSİ 17:00)
            ("backfill_3", 18, 0),    # UTC 18:00 (TSİ 21:00)
        ]:
            scheduler.add_job(
                update,
                CronTrigger(hour=hour, minute=minute),
                misfire_grace_time=3600,
                id=job_id,
                name=f"EVR Backfill Telafi ({hour:02d}:{minute:02d} UTC)",
            )

        logger.info("Zamanlayıcı programı:")
        logger.info("  Ana koşu:    UTC 07:15 (TSİ 10:15)")
        logger.info("  Telafi #1:   UTC 10:30 (TSİ 13:30)")
        logger.info("  Telafi #2:   UTC 14:00 (TSİ 17:00)")
        logger.info("  Telafi #3:   UTC 18:00 (TSİ 21:00)")

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Updater scheduler durduruldu.")
    else:
        update()


if __name__ == "__main__":
    main()
