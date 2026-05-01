"""
EVR Trading Bot — Portfolio API Router
=======================================
Kullanıcının canlı Bybit bakiyesi, varlık dağılımı, işlem geçmişi
ve tarihsel portföy snapshot verilerini sunar.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import ccxt
from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from slowapi import Limiter
from slowapi.util import get_remote_address

from evr_bot.api.deps import get_current_user
from evr_bot.crypto_utils import decrypt
from evr_bot.database import get_db
from evr_bot.market_data import create_exchange, get_balance, get_btc_price
from evr_bot.models import (
    ExecutionStatus,
    PortfolioSnapshot,
    TradeAction,
    TradeLog,
    User,
)

logger = logging.getLogger("evr_bot.api.portfolio")
router = APIRouter(prefix="/api/portfolio")
limiter = Limiter(key_func=get_remote_address)

# Per-user cache: {user_id: (timestamp, response_dict)}
_portfolio_cache: dict[int, tuple[float, dict]] = {}
_PORTFOLIO_CACHE_TTL = 30  # saniye


def _upsert_snapshot(
    db: Session,
    user_id: int,
    btc_amount: float,
    usdt_amount: float,
    total_equity: float,
    btc_price: float,
) -> bool:
    """
    Bugünkü snapshot'ı idempotent olarak oluştur veya güncelle.
    DB-level UNIQUE constraint + IntegrityError catch ile çift katmanlı koruma.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    existing = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_date == today_str,
        )
        .first()
    )

    if existing:
        existing.btc_amount = btc_amount
        existing.usdt_amount = usdt_amount
        existing.total_equity_usdt = total_equity
        existing.btc_price = btc_price
        existing.snapshot_at = datetime.now(timezone.utc)
        db.commit()
        return True

    try:
        new_snap = PortfolioSnapshot(
            user_id=user_id,
            snapshot_date=today_str,
            btc_amount=btc_amount,
            usdt_amount=usdt_amount,
            total_equity_usdt=total_equity,
            btc_price=btc_price,
        )
        db.add(new_snap)
        db.flush()
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        # Başka bir worker aynı anda oluşturdu — güncelle
        existing = (
            db.query(PortfolioSnapshot)
            .filter(
                PortfolioSnapshot.user_id == user_id,
                PortfolioSnapshot.snapshot_date == today_str,
            )
            .first()
        )
        if existing:
            existing.btc_amount = btc_amount
            existing.usdt_amount = usdt_amount
            existing.total_equity_usdt = total_equity
            existing.btc_price = btc_price
            existing.snapshot_at = datetime.now(timezone.utc)
            db.commit()
        return True


@router.get("/summary")
@limiter.limit("5/minute")
def portfolio_summary(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Canlı bakiye + bugünkü snapshot + son gerçek trade'ler."""

    # API key kontrolü
    if not user.api_key_encrypted or not user.api_secret_encrypted:
        return {"has_api_keys": False}

    # Per-user cache kontrolü — Bybit rate limit koruması
    now = time.time()
    cached = _portfolio_cache.get(user.id)
    if cached and now - cached[0] < _PORTFOLIO_CACHE_TTL:
        return cached[1]

    try:
        api_key = decrypt(user.api_key_encrypted)
        api_secret = decrypt(user.api_secret_encrypted)
        exchange = create_exchange(api_key, api_secret)
        balances = get_balance(exchange)
        btc_price = get_btc_price(exchange)
    except ccxt.AuthenticationError:
        return {
            "has_api_keys": True,
            "error": "API anahtarları geçersiz. Lütfen Dashboard > Ayarlar bölümünden güncelleyin.",
        }
    except Exception as exc:
        logger.warning("Portfolio Bybit bağlantı hatası: %s", exc)
        return {
            "has_api_keys": True,
            "error": f"Bybit bağlantı hatası: {str(exc)[:120]}",
        }

    btc_amount = balances.get("btc", 0.0)
    usdt_amount = balances.get("usdt", 0.0)
    total_equity = usdt_amount + (btc_amount * btc_price)

    # Allocation yüzdeleri
    btc_alloc = (btc_amount * btc_price / total_equity * 100) if total_equity > 0 else 0
    usdt_alloc = (usdt_amount / total_equity * 100) if total_equity > 0 else 0

    # Idempotent snapshot
    snapshot_ok = False
    try:
        snapshot_ok = _upsert_snapshot(
            db, user.id, btc_amount, usdt_amount, total_equity, btc_price
        )
    except Exception as exc:
        logger.warning("Snapshot oluşturma hatası: %s", exc)

    # Son gerçek trade'ler (STATE_CHANGE hariç)
    trades = (
        db.query(TradeLog)
        .filter(
            TradeLog.user_id == user.id,
            TradeLog.execution_status == ExecutionStatus.FILLED,
            TradeLog.action.in_([
                TradeAction.BUY,
                TradeAction.SELL,
                TradeAction.SHIELD_SELL,
            ]),
        )
        .order_by(TradeLog.timestamp.desc())
        .limit(50)
        .all()
    )

    recent_trades = [
        {
            "id": t.id,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "action": t.action.value,
            "side": t.side,
            "amount_btc": t.amount_btc,
            "amount_usdt": t.amount_usdt,
            "price": t.price,
            "note": t.note,
        }
        for t in trades
    ]

    result = {
        "has_api_keys": True,
        "total_equity_usdt": round(total_equity, 2),
        "btc_amount": btc_amount,
        "usdt_amount": round(usdt_amount, 2),
        "btc_price": round(btc_price, 2),
        "btc_allocation_pct": round(btc_alloc, 2),
        "usdt_allocation_pct": round(usdt_alloc, 2),
        "recent_trades": recent_trades,
        "snapshot_taken": snapshot_ok,
    }

    # Cache'e yaz
    _portfolio_cache[user.id] = (time.time(), result)
    return result


@router.get("/history")
def portfolio_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tarihsel portfolio snapshot'ları (grafik verisi)."""
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.user_id == user.id)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )

    return {
        "snapshots": [
            {
                "date": s.snapshot_date,
                "snapshot_at": s.snapshot_at.isoformat() if s.snapshot_at else None,
                "btc_amount": s.btc_amount,
                "usdt_amount": s.usdt_amount,
                "total_equity_usdt": s.total_equity_usdt,
                "btc_price": s.btc_price,
            }
            for s in snapshots
        ]
    }
