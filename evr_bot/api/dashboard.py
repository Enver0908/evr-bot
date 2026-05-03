import logging
from pathlib import Path
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from evr_bot.database import get_db
from evr_bot.models import User, TradeLog, ExecutionStatus
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
        stale_state = bs.last_run_at is None or not bs.last_btc_price or not bs.last_ma600
        if not stale_state:
            bot_state = BotStateResponse(
                current_state=bs.current_state.name,
                eski_zirve_fiyati=bs.eski_zirve_fiyati or 0.0,
                breakdown_reference_price=bs.breakdown_reference_price or 0.0,
                last_evr_value=bs.last_evr_value or 0.0,
                last_btc_price=bs.last_btc_price or 0.0,
                last_ma600=bs.last_ma600 or 0.0,
                last_run_at=bs.last_run_at.isoformat() if bs.last_run_at else None,
                shield_pending=bool(bs.shield_pending) if hasattr(bs, 'shield_pending') else False,
            )

    trades = (
        db.query(TradeLog)
        .filter(TradeLog.user_id == user.id)
        .filter(TradeLog.execution_status == ExecutionStatus.FILLED)
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
_live_status_cache = {"time": 0, "data": None}


def _market_series(records):
    """Return BTC, EVR, and MA600 series with DB MA fallback calculation."""
    dates = [r.date_str for r in records]
    btc_prices = [r.btc_price for r in records]

    ma_600 = []
    for i, r in enumerate(records):
        computed_ma = None
        if i >= MA_PERIOD - 1:
            window = btc_prices[i - MA_PERIOD + 1: i + 1]
            if all(price is not None for price in window):
                computed_ma = round(sum(window) / MA_PERIOD, 2)
        ma_600.append(r.ma_600 if r.ma_600 is not None else computed_ma)

    evr_raw = [r.evr_raw for r in records]
    evr_index = [round(r.evr_raw / 10.0, 1) if r.evr_raw is not None else None for r in records]

    return dates, btc_prices, evr_raw, evr_index, ma_600

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
        records = db.query(MarketData).order_by(MarketData.date_str.asc()).all()
        if not records:
            raise HTTPException(status_code=404, detail="Veritabaninda piyasa verisi bulunamadi.")
            
        dates, btc_prices, evr_raw, evr_index, ma_600 = _market_series(records)
        display_start = next((i for i, date in enumerate(dates) if date >= "2021-05-01"), 0)
        dates = dates[display_start:]
        btc_prices = btc_prices[display_start:]
        evr_raw = evr_raw[display_start:]
        evr_index = evr_index[display_start:]
        ma_600 = ma_600[display_start:]

        # EVR verisi olan son tarihe kadar göster (forward-fill yok)
        last_evr_idx = None
        for idx in range(len(evr_raw) - 1, -1, -1):
            if evr_raw[idx] is not None:
                last_evr_idx = idx
                break
        if last_evr_idx is not None and last_evr_idx < len(dates) - 1:
            trim = last_evr_idx + 1
            dates = dates[:trim]
            btc_prices = btc_prices[:trim]
            evr_raw = evr_raw[:trim]
            evr_index = evr_index[:trim]
            ma_600 = ma_600[:trim]

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

        hist_dates, hist_btc, hist_evr, _hist_evr_index, hist_ma = _market_series(valid_records)
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Live status hist okuma hatasi: %s", exc)
        raise HTTPException(status_code=500, detail="Veri okuma hatasi.")

    last_date = hist_dates[-1]
    last_btc = hist_btc[-1]
    ma600 = hist_ma[-1]

    # EVR: forward-fill yok — son gerçek EVR verisini bul
    last_evr_raw = hist_evr[-1]
    evr_source_date = last_date
    if last_evr_raw is None:
        for idx in range(len(hist_evr) - 1, -1, -1):
            if hist_evr[idx] is not None:
                last_evr_raw = hist_evr[idx]
                evr_source_date = hist_dates[idx]
                break
    last_evr = round(last_evr_raw / 10.0, 1) if last_evr_raw is not None else None

    state = "NORMAL"
    ath = 0.0
    breakdown_ref = 0.0

    for i in range(len(hist_btc)):
        price = hist_btc[i]
        evr_val = round((hist_evr[i] if hist_evr[i] is not None else 50) / 10.0, 1)

        curr_ma = hist_ma[i]

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

    if ma600 is not None and last_btc < ma600 and last_evr is not None and last_evr != 0.0:
        state = "SHIELD"
        breakdown_ref = last_btc

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
        "evr_date": evr_source_date,
        "ma600": ma600,
        "state": state,
        "ath": round(ath, 2),
        "breakdown_ref": round(breakdown_ref, 2),
        "action": action,
        "action_label": action_label,
        "action_text": action_text,
        "total_days": len(hist_dates),
        "source": "simulation",
        "disclaimer": "Bu veriler tarihsel simülasyona dayalidir. Gercek bot durumu Dashboard'dan goruntulenebilir.",
    }

    _live_status_cache["data"] = result
    _live_status_cache["time"] = now
    return result
