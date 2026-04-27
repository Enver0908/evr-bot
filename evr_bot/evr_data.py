"""
EVR Trading Bot â€” EVR Endeksi Veri KaynaÄŸÄ± (SQL MÄ°MARÄ°SÄ°)
=========================================================
MarketData tablosundan gÃ¼ncel EVR indeks deÄŸerini okur.
"""
from __future__ import annotations

import logging
from evr_bot.models import MarketData

logger = logging.getLogger("evr_bot.evr_data")

def get_evr_index(db: "Session | None" = None) -> tuple[float, str]:
    """
    GÃ¼ncel EVR Endeksi deÄŸerini ve tarihini dÃ¶ndÃ¼r.

    VeritabanÄ±ndaki MarketData tablosunda tarihe gÃ¶re
    sÄ±ralanmÄ±ÅŸ en son satÄ±rÄ± alÄ±r.
    DÄ±ÅŸarÄ±dan session verilirse onu kullanÄ±r, verilmezse kendi aÃ§Ä±p kapatÄ±r.
    
    Returns:
        (evr_value, date_str) tuple'Ä±.
        evr_value: 0.0-10.0 arasÄ±, hata durumunda -1.0
        date_str: "YYYY-MM-DD" formatÄ±nda, hata durumunda ""
    """
    from evr_bot.database import SessionLocal

    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        last_record = db.query(MarketData).order_by(MarketData.date_str.desc()).first()
        if not last_record:
            logger.warning("VeritabanÄ±nda EVR verisi bulunamadÄ±.")
            return (-1.0, "")

        last_date = last_record.date_str

        # ─── Güvenli Okuma: evr_index None olabilir (örn: EVR scraper'ı o gün çalışmadıysa) ───
        if last_record.evr_index is None:
            # T-1 Tolerance: Bugünün verisi yoksa dünün verisini kullan
            prev_record = db.query(MarketData).order_by(MarketData.date_str.desc()).offset(1).first()
            if prev_record and prev_record.evr_index is not None:
                logger.info("T-1 Tolerans uygulandi. Bugun (%s) icin EVR yok, dunku (%s) deger kullaniliyor: %.1f", last_date, prev_record.date_str, prev_record.evr_index)
                return (float(prev_record.evr_index), prev_record.date_str)
                
            logger.warning(
                "EVR endeksi henuz mevcut degil (tarih: %s). "
                "Muhtemel sebep: EVR scraper o gun basarisiz oldu veya veri henuz guncellenmedi.",
                last_date,
            )
            return (-1.0, last_date)

        evr_val = float(last_record.evr_index)
        logger.info("EVR Endeksi: %.1f (SQL Tarih: %s)", evr_val, last_date)
        return (evr_val, last_date)

    except Exception as exc:
        logger.exception("SQL EVR verisi okuma hatasÄ±: %s", exc)
        return (-1.0, "")
    finally:
        if owns_session:
            db.close()
