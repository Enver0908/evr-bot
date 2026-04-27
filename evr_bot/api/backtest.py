from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from evr_bot.database import get_db
from evr_bot.api.schemas import BacktestRequest
from evr_bot.api.deps import get_current_active_user
from evr_bot.models import User
from evr_bot.config import MA_PERIOD, EVR_BUY_THRESHOLD, EVR_SELL_THRESHOLD, BUY_PERCENT, SELL_PERCENT, BREAKDOWN_DROP_PERCENT, MIN_ORDER_USDT

from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

def _load_backtest_data(db: Session) -> dict:
    """Tum tarihsel verileri SQL'den yukle ve birlestir."""
    from evr_bot.models import MarketData
    data = {}  # {date_str: {"btc_price": float, "evr_raw": float|None}}

    records = db.query(MarketData).order_by(MarketData.date_str.asc()).all()
    for row in records:
        if not row.date_str:
            continue
        # Backtest motoru evr_raw uzerinden calistigi isin
        data[row.date_str] = {
            "btc_price": row.btc_price, 
            "evr_raw": float(row.evr_raw) if row.evr_raw is not None else None
        }
    return data


@router.post("/api/backtest")
@limiter.limit("3/minute")
def run_backtest(request: Request, req: BacktestRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """
    Belirtilen tarih araliginda strateji backtesti calistirir.
    Kimlik dogrulama gerektirir — DoS koruması.
    """
    all_data = _load_backtest_data(db)
    if not all_data:
        raise HTTPException(status_code=500, detail="Tarihsel veri yuklenemedi.")

    sorted_dates = sorted(all_data.keys())
    if not sorted_dates:
        raise HTTPException(status_code=500, detail="Tarihsel veri bos.")

    start_date = req.start_date.strip()
    end_date = req.end_date.strip()

    # Tarih formati dogrulama (YYYY-MM-DD)
    from datetime import datetime as _dt
    for label, val in [("Baslangic", start_date), ("Bitis", end_date)]:
        try:
            _dt.strptime(val, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"{label} tarihi gecersiz format: '{val}'. YYYY-MM-DD bekleniyor.",
            )

    min_date = sorted_dates[0]
    max_date = sorted_dates[-1]

    if start_date < min_date:
        start_date = min_date
    if end_date > max_date:
        end_date = max_date
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="Baslangic tarihi bitis tarihinden once olmali.")

    all_prices = [(d, all_data[d]["btc_price"]) for d in sorted_dates if all_data[d]["btc_price"] > 0]
    price_index = {d: i for i, (d, _) in enumerate(all_prices)}

    def calc_ma600(date_str: str) -> float | None:
        idx = price_index.get(date_str)
        if idx is None or idx < MA_PERIOD - 1:
            return None
        window = [all_prices[i][1] for i in range(idx - MA_PERIOD + 1, idx + 1)]
        return sum(window) / len(window)

    state = "NORMAL"
    ath = 0.0
    breakdown_ref = 0.0

    trades = []
    state_timeline = []
    equity_curve = []
    warnings = []

    usdt_balance = req.initial_capital
    btc_balance = 0.0
    peak_equity = req.initial_capital
    max_drawdown = 0.0
    start_btc_price = None
    end_btc_price = None
    
    capital_initialized = False

    for i, day_str in enumerate(sorted_dates):
        if day_str > end_date:
            break
            
        day_data = all_data[day_str]
        btc_price = day_data["btc_price"]
        evr_raw = day_data["evr_raw"]
        
        # T-1 Tolerance for Backtest
        if evr_raw is None and i > 0:
            prev_day_str = sorted_dates[i-1]
            if all_data[prev_day_str]["evr_raw"] is not None:
                evr_raw = all_data[prev_day_str]["evr_raw"]

        if btc_price <= 0:
            continue

        ma600 = calc_ma600(day_str)

        if evr_raw is None:
            evr = None
            if day_str >= start_date and (len(warnings) == 0 or "EVR verisi yok" not in warnings[-1]):
                warnings.append(f"{day_str}: Bu tarihte EVR verisi yok. Islem dongusu atlandi (Trade Skip).")
        else:
            evr = round(evr_raw / 10.0, 1)

        if state == "NORMAL" and btc_price > ath:
            ath = btc_price
            
        is_live = day_str >= start_date

        if is_live and not capital_initialized:
            capital_initialized = True
            usdt_balance = req.initial_capital
            btc_balance = 0.0
            peak_equity = req.initial_capital
            start_btc_price = btc_price
            state_timeline.append({
                "date": day_str,
                "state": state,
                "reason": f"Simulasyon baslangici. (Gecmisten devralinan ATH: ${ath:,.0f})",
            })

        if is_live:
            end_btc_price = btc_price
            total_equity = usdt_balance + (btc_balance * btc_price)
            if total_equity > peak_equity:
                peak_equity = total_equity
            dd = (peak_equity - total_equity) / peak_equity * 100 if peak_equity > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        if state == "NORMAL":
            if ma600 is not None and btc_price < ma600:
                breakdown_ref = btc_price
                state = "SHIELD"
                if is_live:
                    state_timeline.append({
                        "date": day_str,
                        "state": state,
                        "reason": f"Fiyat (${btc_price:,.0f}) < MA600 (${ma600:,.0f}). Nakit moduna gecildi.",
                    })
                    if btc_balance > 0:
                        sell_usdt = btc_balance * btc_price
                        trades.append({
                            "date": day_str,
                            "action": "SHIELD_SELL",
                            "side": "sell",
                            "price": btc_price,
                            "amount_btc": round(btc_balance, 8),
                            "amount_usdt": round(sell_usdt, 2),
                            "evr": evr,
                            "state": state,
                            "note": f"Kalkan: Tum BTC ({btc_balance:.6f}) satildi",
                        })
                        usdt_balance += sell_usdt
                        btc_balance = 0.0
            else:
                if is_live and evr is not None:
                    total = usdt_balance + (btc_balance * btc_price)
                    if evr <= EVR_BUY_THRESHOLD:
                        buy_usdt = total * BUY_PERCENT
                        if buy_usdt > usdt_balance:
                            buy_usdt = usdt_balance
                        if buy_usdt >= MIN_ORDER_USDT:
                            buy_btc = buy_usdt / btc_price
                            usdt_balance -= buy_usdt
                            btc_balance += buy_btc
                            trades.append({
                                "date": day_str,
                                "action": "BUY",
                                "side": "buy",
                                "price": btc_price,
                                "amount_btc": round(buy_btc, 8),
                                "amount_usdt": round(buy_usdt, 2),
                                "evr": evr,
                                "state": state,
                                "note": f"EVR {evr:.1f} <= {EVR_BUY_THRESHOLD}",
                            })
                    elif evr >= EVR_SELL_THRESHOLD:
                        sell_btc = btc_balance * SELL_PERCENT
                        sell_usdt = sell_btc * btc_price
                        if sell_usdt >= MIN_ORDER_USDT:
                            btc_balance -= sell_btc
                            usdt_balance += sell_usdt
                            trades.append({
                                "date": day_str,
                                "action": "SELL",
                                "side": "sell",
                                "price": btc_price,
                                "amount_btc": round(sell_btc, 8),
                                "amount_usdt": round(sell_usdt, 2),
                                "evr": evr,
                                "state": state,
                                "note": f"EVR {evr:.1f} >= {EVR_SELL_THRESHOLD}",
                            })

        elif state == "SHIELD":
            drop_threshold = breakdown_ref * (1 - BREAKDOWN_DROP_PERCENT)
            if ma600 is not None and btc_price >= ma600:
                state = "NORMAL"
                if is_live:
                    state_timeline.append({
                        "date": day_str,
                        "state": state,
                        "reason": f"Fiyat (${btc_price:,.0f}) >= MA600 (${ma600:,.0f}). Kalkan Reset.",
                    })
                    total = usdt_balance + (btc_balance * btc_price)
                    if evr is not None and evr <= EVR_BUY_THRESHOLD:
                        buy_usdt = total * BUY_PERCENT
                        if buy_usdt > usdt_balance:
                            buy_usdt = usdt_balance
                        if buy_usdt >= MIN_ORDER_USDT:
                            buy_btc = buy_usdt / btc_price
                            usdt_balance -= buy_usdt
                            btc_balance += buy_btc
                            trades.append({
                                "date": day_str,
                                "action": "BUY",
                                "side": "buy",
                                "price": btc_price,
                                "amount_btc": round(buy_btc, 8),
                                "amount_usdt": round(buy_usdt, 2),
                                "evr": evr,
                                "state": state,
                                "note": f"Reset sonrasi alis: EVR {evr:.1f}",
                            })

            elif evr == 0.0 or btc_price <= drop_threshold:
                reason = "EVR=0.0" if evr == 0.0 else f"Fiyat (${btc_price:,.0f}) <= %45 dusus"
                state = "BLIND"
                if is_live:
                    state_timeline.append({
                        "date": day_str,
                        "state": state,
                        "reason": f"Dip bolgesi: {reason}. MA600 iptal.",
                    })
                    total = usdt_balance + (btc_balance * btc_price)
                    if evr is not None and evr <= EVR_BUY_THRESHOLD:
                        buy_usdt = total * BUY_PERCENT
                        if buy_usdt > usdt_balance:
                            buy_usdt = usdt_balance
                        if buy_usdt >= MIN_ORDER_USDT:
                            buy_btc = buy_usdt / btc_price
                            usdt_balance -= buy_usdt
                            btc_balance += buy_btc
                            trades.append({
                                "date": day_str,
                                "action": "BUY",
                                "side": "buy",
                                "price": btc_price,
                                "amount_btc": round(buy_btc, 8),
                                "amount_usdt": round(buy_usdt, 2),
                                "evr": evr,
                                "state": state,
                                "note": f"Blind mod alis: EVR {evr:.1f}",
                            })

        elif state == "BLIND":
            if ath > 0 and btc_price >= ath:
                state = "NORMAL"
                if is_live:
                    state_timeline.append({
                        "date": day_str,
                        "state": state,
                        "reason": f"Fiyat (${btc_price:,.0f}) >= Eski ATH (${ath:,.0f}).",
                    })

            if state == "BLIND" and is_live and evr is not None:
                total = usdt_balance + (btc_balance * btc_price)
                if evr <= EVR_BUY_THRESHOLD:
                    buy_usdt = total * BUY_PERCENT
                    if buy_usdt > usdt_balance:
                        buy_usdt = usdt_balance
                    if buy_usdt >= MIN_ORDER_USDT:
                        buy_btc = buy_usdt / btc_price
                        usdt_balance -= buy_usdt
                        btc_balance += buy_btc
                        trades.append({
                            "date": day_str,
                            "action": "BUY",
                            "side": "buy",
                            "price": btc_price,
                            "amount_btc": round(buy_btc, 8),
                            "amount_usdt": round(buy_usdt, 2),
                            "evr": evr,
                            "state": state,
                            "note": f"Blind mod alis: EVR {evr:.1f}",
                        })
                elif evr >= EVR_SELL_THRESHOLD:
                    sell_btc = btc_balance * SELL_PERCENT
                    sell_usdt = sell_btc * btc_price
                    if sell_usdt >= MIN_ORDER_USDT:
                        btc_balance -= sell_btc
                        usdt_balance += sell_usdt
                        trades.append({
                            "date": day_str,
                            "action": "SELL",
                            "side": "sell",
                            "price": btc_price,
                            "amount_btc": round(sell_btc, 8),
                            "amount_usdt": round(sell_usdt, 2),
                            "evr": evr,
                            "state": state,
                            "note": f"Blind mod satis: EVR {evr:.1f}",
                        })

        if is_live:
            total_equity = usdt_balance + (btc_balance * btc_price)
            equity_curve.append({
                "date": day_str,
                "equity": round(total_equity, 2),
                "usdt": round(usdt_balance, 2),
                "btc": round(btc_balance, 8),
            })

    final_equity = usdt_balance + (btc_balance * (end_btc_price or 0))
    net_pnl_pct = ((final_equity - req.initial_capital) / req.initial_capital) * 100

    buy_and_hold_pct = 0.0
    if start_btc_price and end_btc_price and start_btc_price > 0:
        buy_and_hold_pct = ((end_btc_price - start_btc_price) / start_btc_price) * 100

    buy_trades = [t for t in trades if t["action"] == "BUY"]
    sell_trades = [t for t in trades if t["action"] in ("SELL", "SHIELD_SELL")]

    return {
        "initial_capital": req.initial_capital,
        "final_capital": round(final_equity, 2),
        "net_pnl_pct": round(net_pnl_pct, 2),
        "total_trades": len(trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "max_drawdown_pct": round(max_drawdown, 2),
        "buy_and_hold_pct": round(buy_and_hold_pct, 2),
        "start_date": start_date,
        "end_date": end_date,
        "start_btc_price": start_btc_price,
        "end_btc_price": end_btc_price,
        "final_btc_balance": round(btc_balance, 8),
        "final_usdt_balance": round(usdt_balance, 2),
        "state_timeline": state_timeline,
        "trades": trades,
        "equity_curve": equity_curve,
        "warnings": warnings,
    }
