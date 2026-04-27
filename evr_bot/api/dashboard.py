import logging
from pathlib import Path
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from evr_bot.database import get_db
from evr_bot.models import User, TradeLog
from evr_bot.api.schemas import DashboardResponse, UserProfile, BotStateResponse, TradeLogResponse
from evr_bot.api.deps import get_current_user
from evr_bot.api.auth import limiter
from evr_bot.config import (
    BASE_DIR, MA_PERIOD, EVR_BUY_THRESHOLD, EVR_SELL_THRESHOLD,
    BUY_PERCENT, SELL_PERCENT, BREAKDOWN_DROP_PERCENT, MIN_ORDER_USDT
)

router = APIRouter()
logger = logging.getLogger("evr_bot.api.dashboard")



@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kullanici dashboard: profil, bot durumu ve son islemler."""
    profile = UserProfile(
        id=user.id,
        email=user.email,
        subscription_status=user.subscription_status.value,
        is_lifetime_member=bool(user.is_lifetime_member),
        has_api_keys=bool(user.api_key_encrypted),
        created_at=user.created_at.isoformat() if user.created_at else None,
    )

    bot_state = None
    if user.bot_state:
        bs = user.bot_state
        bot_state = BotStateResponse(
            current_state=bs.current_state.name,
            eski_zirve_fiyati=bs.eski_zirve_fiyati or 0.0,
            breakdown_reference_price=bs.breakdown_reference_price or 0.0,
            last_evr_value=bs.last_evr_value or 0.0,
            last_btc_price=bs.last_btc_price or 0.0,
            last_ma600=bs.last_ma600 or 0.0,
            last_run_at=bs.last_run_at.isoformat() if bs.last_run_at else None,
        )

    trades = (
        db.query(TradeLog)
        .filter(TradeLog.user_id == user.id)
        .order_by(TradeLog.timestamp.desc())
        .limit(50)
        .all()
    )
    recent_trades = [
        TradeLogResponse(
            id=t.id,
            timestamp=t.timestamp.isoformat(),
            action=t.action.value,
            side=t.side,
            amount_btc=t.amount_btc,
            amount_usdt=t.amount_usdt,
            price=t.price,
            evr_value=t.evr_value,
            bot_state_at=t.bot_state_at,
            note=t.note,
        )
        for t in trades
    ]

    return DashboardResponse(
        user=profile,
        bot_state=bot_state,
        recent_trades=recent_trades,
    )


_chart_cache = {"time": 0, "data": None}

@router.get("/api/chart-data")
@limiter.limit("10/minute")
def get_chart_data(request: Request, db: Session = Depends(get_db)):
    """
    Tarihsel BTC fiyat + EVR endeks verisini ve hesaplanmis MA_600'u dondur.
    Public endpoint — MarketData SQL tablosundan veri çeker.
    """
    now = time.time()
    if now - _chart_cache["time"] < 60 and _chart_cache["data"]:
        return _chart_cache["data"]

    from evr_bot.models import MarketData
    
    try:
        records = db.query(MarketData).filter(MarketData.date_str >= "2021-05-01").order_by(MarketData.date_str.asc()).all()
        if not records:
            raise HTTPException(status_code=404, detail="Veritabaninda piyasa verisi bulunamadi.")
            
        dates = [r.date_str for r in records]
        btc_prices = [r.btc_price for r in records]
        evr_raw = [r.evr_raw for r in records]
        evr_index = [r.evr_index for r in records]
        ma_600 = [r.ma_600 for r in records]
        
        result = {
            "dates": dates,
            "btc_prices": btc_prices,
            "evr_raw": evr_raw,
            "evr_index": evr_index,
            "ma_600": ma_600,
            "total_points": len(dates),
        }
        
        _chart_cache["data"] = result
        _chart_cache["time"] = now
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Chart data DB okuma hatasi: %s", exc)
        raise HTTPException(status_code=500, detail="Veritabanindan veri okuma hatasi.")


@router.get("/api/strategy-info")
def get_strategy_info():
    """Strateji parametrelerini dondur — seffaflik icin."""
    return {
        "ma_period": MA_PERIOD,
        "evr_buy_threshold": EVR_BUY_THRESHOLD,
        "evr_sell_threshold": EVR_SELL_THRESHOLD,
        "buy_percent": BUY_PERCENT,
        "sell_percent": SELL_PERCENT,
        "breakdown_drop_percent": BREAKDOWN_DROP_PERCENT,
        "min_order_usdt": MIN_ORDER_USDT,
    }


_live_status_cache = {"time": 0, "data": None}

@router.get("/api/live-status")
@limiter.limit("10/minute")
def get_live_status(request: Request, db: Session = Depends(get_db)):
    """
    Guncel EVR, BTC, MA600 ve durum makinesi durumunu hesapla.
    Public endpoint — MarketData SQL tablosundan okur.
    """
    now = time.time()
    if now - _live_status_cache["time"] < 60 and _live_status_cache["data"]:
        return _live_status_cache["data"]

    from evr_bot.models import MarketData
    
    try:
        records = db.query(MarketData).order_by(MarketData.date_str.asc()).all()
        if not records:
            raise HTTPException(status_code=404, detail="Veritabaninda piyasa verisi yok.")

        # ── Bozuk kayıtları filtrele: btc_price None olan satırlar hesaplamayı çökertir ──
        valid_records = [r for r in records if r.btc_price is not None]
        if not valid_records:
            raise HTTPException(status_code=404, detail="Veritabaninda gecerli piyasa verisi yok.")

        hist_dates = [r.date_str for r in valid_records]
        hist_btc = [r.btc_price for r in valid_records]
        # EVR None olabilir — güvenli okuma ile varsayılan 50 (Nötr) değeri atanır. T-1 Toleransı uygulanır.
        hist_evr = []
        for i, r in enumerate(valid_records):
            if r.evr_raw is not None:
                hist_evr.append(r.evr_raw)
            else:
                if i > 0 and valid_records[i-1].evr_raw is not None:
                    hist_evr.append(valid_records[i-1].evr_raw)
                else:
                    hist_evr.append(50)
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Live status hist okuma hatasi: %s", exc)
        raise HTTPException(status_code=500, detail="Veri okuma hatasi.")

    last_date = hist_dates[-1]
    
    # T-1 Tolerance for Dashboard
    last_evr_raw = valid_records[-1].evr_raw
    if last_evr_raw is None and len(valid_records) >= 2:
        last_evr_raw = valid_records[-2].evr_raw
        
    last_evr = round(last_evr_raw / 10.0, 1) if last_evr_raw is not None else 5.0
    last_btc = hist_btc[-1]
    ma600 = valid_records[-1].ma_600

    state = "NORMAL"
    ath = 0.0
    breakdown_ref = 0.0

    for i in range(len(hist_btc)):
        price = hist_btc[i]
        evr_val = round(hist_evr[i] / 10.0, 1)

        if i >= MA_PERIOD - 1:
            curr_ma = sum(hist_btc[i - MA_PERIOD + 1: i + 1]) / MA_PERIOD
        else:
            curr_ma = None

        if state == "NORMAL" and price > ath:
            ath = price

        if state == "NORMAL":
            if curr_ma is not None and price < curr_ma:
                breakdown_ref = price
                state = "SHIELD"
        elif state == "SHIELD":
            if curr_ma is not None and price >= curr_ma:
                state = "NORMAL"
            elif evr_val == 0.0 or (breakdown_ref > 0 and price <= breakdown_ref * (1 - BREAKDOWN_DROP_PERCENT)):
                state = "BLIND"
        elif state == "BLIND":
            if ath > 0 and price >= ath:
                state = "NORMAL"

    if last_evr_raw is None:
        action = "SKIP"
        action_label = "Veri Yok / Trade Skip"
        action_text = "EVR verisi alinamadi. Motor bugun islem yapmayacak."
    elif state == "SHIELD":
        action = "SHIELD"
        action_label = "Nakit Modunda"
        action_text = f"Fiyat (${last_btc:,.0f}) MA_600'un (${ma600:,.0f}) altinda. Nakit modunda bekleniyor." if ma600 else "Shield modunda."
    elif state == "BLIND":
        action = "BLIND"
        action_label = "Dipten Mal Toplama"
        action_text = "Dip bolgesi tespit edildi. MA_600 devre disi, sadece EVR kurallari gecerli."
    elif last_evr <= EVR_BUY_THRESHOLD:
        action = "BUY"
        action_label = "Alis Sinyali"
        action_text = f"EVR {last_evr:.1f} — Asiri korku bolgesi. Kasanin %{BUY_PERCENT*100:.0f}'i ile BTC alinacak."
    elif last_evr >= EVR_SELL_THRESHOLD:
        action = "SELL"
        action_label = "Satis Sinyali"
        action_text = f"EVR {last_evr:.1f} — Asiri acgozluluk bolgesi. BTC'nin %{SELL_PERCENT*100:.0f}'i satilacak."
    else:
        action = "HOLD"
        action_label = "Bekle"
        action_text = f"EVR {last_evr:.1f} — Notr bolge. Islem sinyali yok."

    result = {
        "date": last_date,
        "btc_price": last_btc,
        "evr_raw": last_evr_raw,
        "evr_index": last_evr,
        "ma600": ma600,
        "state": state,
        "ath": round(ath, 2),
        "breakdown_ref": round(breakdown_ref, 2),
        "action": action,
        "action_label": action_label,
        "action_text": action_text,
        "total_days": len(hist_dates),
    }

    _live_status_cache["data"] = result
    _live_status_cache["time"] = now
    return result
