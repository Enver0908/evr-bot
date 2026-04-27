"""
EVR Trading Bot - Scheduler tabanli ana dongu.

Job 1 - Shield Check:
  Referans fiyat + MA600 ile kalkan kontrolu.

Job 2 - EVR Cycle:
  Guncel EVR ile alim/satim kararlarinin uygulanmasi.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from filelock import FileLock
from sqlalchemy import or_

from evr_bot.config import (
    EVR_CYCLE_UTC_HOUR,
    EVR_CYCLE_UTC_MINUTE,
    LOG_FILE,
    SHIELD_CHECK_UTC_HOUR,
    SHIELD_CHECK_UTC_MINUTE,
)
from evr_bot.database import SessionLocal, init_db
from evr_bot.models import SubscriptionStatus, User
from evr_bot.trading_engine import TradingEngine

_rotating_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_rotating_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)-24s | %(levelname)-8s | %(message)s")
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-8s | %(message)s",
    handlers=[
        _rotating_handler,
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("evr_bot.main")


def _write_heartbeat() -> None:
    """Docker healthcheck icin heartbeat dosyasini gunceller."""
    try:
        data_dir = Path(os.getenv("DATA_DIR", str(Path(LOG_FILE).parent)))
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "bot_heartbeat").touch()
    except Exception as exc:
        logger.warning("Heartbeat yazilamadi: %s", exc)


def _scheduler_lock_path() -> Path:
    """Tum process/containerlar icin ortak lock dosya yolunu dondur."""
    data_dir = Path(os.getenv("DATA_DIR", str(Path(LOG_FILE).parent)))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "bot_scheduler.lock"


def _get_active_users(db):
    """
    Aktif ve suresi dolmamis aboneleri dondur.

    Suresi dolan abonelikler bu dongude otomatik olarak INACTIVE yapilir.
    """
    candidates = (
        db.query(User)
        .filter(or_(User.subscription_status == SubscriptionStatus.ACTIVE, User.is_lifetime_member.is_(True)))
        .filter(User.api_key_encrypted.isnot(None))
        .filter(User.api_secret_encrypted.isnot(None))
        .all()
    )

    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    active_users = []

    for user in candidates:
        if user.is_lifetime_member:
            active_users.append(user)
            continue

        if user.subscription_expires is not None:
            exp_naive = user.subscription_expires.replace(tzinfo=None)
            if exp_naive < now_utc_naive:
                logger.warning(
                    "Abonelik suresi doldu: %s (ID: %d, Bitis: %s). Otomatik devre disi birakildi.",
                    user.email, user.id, user.subscription_expires.isoformat(),
                )
                user.subscription_status = SubscriptionStatus.INACTIVE
                db.commit()
                continue

        active_users.append(user)

    return active_users


def job_shield_check():
    """Tum aktif kullanicilar icin shield kontrolu calistir."""
    logger.info("=" * 70)
    logger.info("SHIELD CHECK baslatiliyor... (%s UTC)", datetime.now(timezone.utc).isoformat())
    logger.info("=" * 70)

    db_main = SessionLocal()
    try:
        users = _get_active_users(db_main)
    finally:
        db_main.close()

    if not users:
        logger.warning("Aktif abone kullanici bulunamadi.")
        _write_heartbeat()
        logger.info("Shield check tamamlandi.")
        return

    logger.info("Aktif kullanici: %d", len(users))
    user_ids = [user.id for user in users]

    for uid in user_ids:
        db_user = SessionLocal()
        try:
            attached_user = db_user.query(User).get(uid)
            if not attached_user:
                continue

            logger.info("- Shield Check: %s (ID: %d) -", attached_user.email, attached_user.id)
            engine = TradingEngine(db_user, attached_user)
            result = engine.run_shield_check()

            if result["success"]:
                logger.info(
                    "OK -> Durum=%s BTC=%.2f MA600=%.2f",
                    result.get("state", "?"),
                    result.get("btc_price", 0),
                    result.get("ma600", 0),
                )
            else:
                logger.error("HATA -> %s", result.get("error", "?"))
        except Exception as exc:
            logger.exception("Kullanici ID %d icin shield check hatasi: %s", uid, exc)
        finally:
            db_user.close()

    _write_heartbeat()
    logger.info("Shield check tamamlandi.")


def job_evr_cycle():
    """Tum aktif kullanicilar icin EVR dongusunu calistir."""
    logger.info("=" * 70)
    logger.info("EVR CYCLE baslatiliyor... (%s UTC)", datetime.now(timezone.utc).isoformat())
    logger.info("=" * 70)

    db_main = SessionLocal()
    try:
        users = _get_active_users(db_main)
    finally:
        db_main.close()

    if not users:
        logger.warning("Aktif abone kullanici bulunamadi.")
        _write_heartbeat()
        logger.info("EVR cycle tamamlandi.")
        return

    logger.info("Aktif kullanici: %d", len(users))
    user_ids = [user.id for user in users]

    for uid in user_ids:
        db_user = SessionLocal()
        try:
            attached_user = db_user.query(User).get(uid)
            if not attached_user:
                continue

            logger.info("- EVR Cycle: %s (ID: %d) -", attached_user.email, attached_user.id)
            engine = TradingEngine(db_user, attached_user)
            result = engine.run_evr_cycle()

            if result["success"]:
                logger.info(
                    "OK -> Durum=%s EVR=%.1f Aksiyon=%s",
                    result.get("state", "?"),
                    result.get("evr", 0),
                    result.get("action", "?"),
                )
            else:
                logger.error("HATA -> %s", result.get("error", "?"))
        except Exception as exc:
            logger.exception("Kullanici ID %d icin EVR cycle hatasi: %s", uid, exc)
        finally:
            db_user.close()

    _write_heartbeat()
    logger.info("EVR cycle tamamlandi.")


def main():
    """Ana giris noktasi: scheduler veya --once modunda calistir."""
    import argparse

    parser = argparse.ArgumentParser(description="EVR Trading Bot - Scheduler")
    parser.add_argument("--once", action="store_true", help="Tek sefer calistir (test)")
    parser.add_argument("--shield", action="store_true", help="Sadece shield check calistir")
    parser.add_argument("--evr", action="store_true", help="Sadece EVR cycle calistir")
    args = parser.parse_args()

    init_db()
    logger.info("Veritabani hazir.")
    _write_heartbeat()  # İlk açılışta Docker healthcheck'in unhealthy kalmaması için
    lock = FileLock(str(_scheduler_lock_path()))

    if args.once or args.shield or args.evr:
        try:
            with lock.acquire(timeout=0):
                if args.shield:
                    job_shield_check()
                elif args.evr:
                    job_evr_cycle()
                else:
                    job_shield_check()
                    job_evr_cycle()
        except TimeoutError:
            logger.warning("Baska bir bot sureci calisiyor; tek seferlik komut atlandi.")
        return

    logger.info("Scheduler lock bekleniyor: %s", _scheduler_lock_path())
    lock.acquire()
    logger.info("Scheduler lock alindi.")
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        job_shield_check,
        CronTrigger(hour=SHIELD_CHECK_UTC_HOUR, minute=SHIELD_CHECK_UTC_MINUTE),
        id="shield_check",
        name="Referans Fiyat + Shield Kontrolu",
        misfire_grace_time=3600,
        max_instances=1,
    )
    scheduler.add_job(
        job_evr_cycle,
        CronTrigger(hour=EVR_CYCLE_UTC_HOUR, minute=EVR_CYCLE_UTC_MINUTE),
        id="evr_cycle",
        name="EVR Endeksi Kontrolu",
        misfire_grace_time=3600,
        max_instances=1,
    )

    logger.info("=" * 70)
    logger.info("EVR Trading Bot - Scheduler baslatiliyor")
    logger.info("  Shield Check: Her gun UTC %02d:%02d", SHIELD_CHECK_UTC_HOUR, SHIELD_CHECK_UTC_MINUTE)
    logger.info("  EVR Cycle:    Her gun UTC %02d:%02d", EVR_CYCLE_UTC_HOUR, EVR_CYCLE_UTC_MINUTE)
    logger.info("=" * 70)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Bot durduruldu.")
        scheduler.shutdown()
    finally:
        if lock.is_locked:
            lock.release()


if __name__ == "__main__":
    main()
