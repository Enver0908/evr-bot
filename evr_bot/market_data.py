"""
EVR Trading Bot — Piyasa Verisi (Bybit via ccxt)
==================================================
BTC/USDT verilerini veritabanı ve Bybit ccxt üzerinden alır.

Yeni Mimari:
- MA_600: SQL MarketData tablosundan hesaplanır
- Günlük kapanış: SQL MarketData tablosuna daily_updater üzerinden beslenir
- Anlık fiyat: Bybit ticker'dan
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
import ccxt

from evr_bot.config import (
    BYBIT_TESTNET, SYMBOL, MA_PERIOD,
)

logger = logging.getLogger("evr_bot.market_data")


def create_exchange(api_key: str, api_secret: str) -> ccxt.bybit:
    """Bybit exchange nesnesi oluştur (Testnet destekli)."""
    exchange = ccxt.bybit({
        "apiKey": api_key,
        "secret": api_secret,
        "sandbox": BYBIT_TESTNET,
        "enableRateLimit": True,
        "options": {
            "defaultType": "spot",
        },
    })
    return exchange


def get_btc_price(exchange: Optional[ccxt.bybit] = None) -> float:
    """Güncel BTC/USDT fiyatını çek (anlık ticker)."""
    if exchange is None:
        exchange = ccxt.bybit({"sandbox": BYBIT_TESTNET})
    ticker = exchange.fetch_ticker(SYMBOL)
    price = float(ticker["last"])
    logger.info("BTC/USDT fiyat: %.2f", price)
    return price


# ═══════════════════════════════════════════════════════════════════════════════
# MA_600 — DB TABANLI (YENİ KURUMSAL MİMARİ)
# ═══════════════════════════════════════════════════════════════════════════════

def get_ma600_from_db(db: "Session | None" = None) -> float:
    """
    MarketData tablosundan (veya son 600 günden) hesaplanmış MA_600 değerini döner.
    Dışarıdan session verilirse onu kullanır, verilmezse kendi açıp kapatır.
    """
    from evr_bot.database import SessionLocal
    from evr_bot.models import MarketData
    
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        # En güncel MA_600'ü çek
        latest = db.query(MarketData).order_by(MarketData.date_str.desc()).first()
        if not latest:
            raise ValueError("MA_600 hesaplanamadı: MarketData tablosu boş veya bulunamadı.")
            
        if latest.ma_600 is not None:
            logger.info(f"MA_{MA_PERIOD} = {latest.ma_600:.2f} (DB tabanlı)")
            return latest.ma_600
        
        # Eğer henüz hesaplanmamışsa son 600 günü çekip hesapla
        records = db.query(MarketData).order_by(MarketData.date_str.desc()).limit(MA_PERIOD).all()
        closes = [float(r.btc_price) for r in records if r.btc_price is not None]

        if len(closes) < MA_PERIOD:
            logger.warning(
                "MA_%d için yeterli veri yok (mevcut: %d). Mevcut veriyle hesaplanıyor.",
                MA_PERIOD, len(closes),
            )
            
        ma = round(sum(closes) / len(closes), 2) if closes else 0.0
        logger.info(f"MA_{MA_PERIOD} = {ma:.2f} ({len(closes)} gün, DB hesaplamalı)")
        return ma
    finally:
        if owns_session:
            db.close()


def get_last_db_date(db: "Session | None" = None) -> str:
    """MarketData SQL tablosundaki en son tarihi döner."""
    from evr_bot.database import SessionLocal
    from evr_bot.models import MarketData
    
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        latest = db.query(MarketData).order_by(MarketData.date_str.desc()).first()
        return latest.date_str if latest else ""
    finally:
        if owns_session:
            db.close()

def get_reference_price_from_db(db: "Session | None" = None) -> tuple[float, str]:
    """MarketData SQL tablosundan en son referans fiyatını ve tarihini döner."""
    from evr_bot.database import SessionLocal
    from evr_bot.models import MarketData
    
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        latest = db.query(MarketData).order_by(MarketData.date_str.desc()).first()
        if not latest:
            raise ValueError("Referans fiyatı bulunamadı: MarketData boş.")
        return (latest.btc_price, latest.date_str)
    finally:
        if owns_session:
            db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# BAKİYE & EMİR
# ═══════════════════════════════════════════════════════════════════════════════

def get_balance(exchange: ccxt.bybit) -> dict:
    """
    Kullanıcının spot bakiyesini sorgula.

    Returns:
        {"usdt": float, "btc": float}
    """
    balance = exchange.fetch_balance()
    usdt = float(balance.get("USDT", {}).get("free", 0.0))
    btc = float(balance.get("BTC", {}).get("free", 0.0))
    logger.info("Bakiye → USDT: %.2f | BTC: %.8f", usdt, btc)
    return {"usdt": usdt, "btc": btc}


def place_market_order(
    exchange: ccxt.bybit,
    side: str,
    amount_btc: float,
    client_order_id: str | None = None,
) -> dict:
    """
    Piyasa fiyatından market order gönder.

    Args:
        exchange: ccxt exchange nesnesi
        side: "buy" veya "sell"
        amount_btc: BTC miktarı

    Returns:
        ccxt order response dict
    """
    logger.info("Order gönderiliyor: %s %.8f BTC", side.upper(), amount_btc)

    # Market bilgisini yükle (cachelenir)
    if not exchange.markets:
        exchange.load_markets()
    
    # Precision normalizasyonu
    amount_btc = float(exchange.amount_to_precision(SYMBOL, amount_btc))
    
    # Min-lot kontrolü
    market_info = exchange.market(SYMBOL)
    min_amount = market_info.get("limits", {}).get("amount", {}).get("min", 0)
    if amount_btc < min_amount:
        raise ValueError(f"Miktar ({amount_btc}) minimum lot altında ({min_amount})")

    params = {}
    if client_order_id:
        # Bybit/ccxt tarafinda istemci emir kimligini tasimak recovery akisini kolaylastirir.
        params["clientOrderId"] = client_order_id
        params["orderLinkId"] = client_order_id

    order = exchange.create_order(
        symbol=SYMBOL,
        type="market",
        side=side,
        amount=amount_btc,
        params=params,
    )

    logger.info(
        "Order tamamlandı → id=%s side=%s amount=%.8f price=%.2f",
        order.get("id"), order.get("side"),
        order.get("filled", 0), order.get("average", 0),
    )
    return order
