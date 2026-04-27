"""
EVR Trading Bot - Cekirdek trading engine.

Durumlar:
- NORMAL: EVR kurallari ile alim/satim
- SHIELD: MA600 alti, nakit modunda bekleme
- BLIND: dip bolgesi, MA600 devre disi
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

import ccxt
from sqlalchemy.orm import Session

from evr_bot.config import (
    BREAKDOWN_DROP_PERCENT,
    BUY_PERCENT,
    EVR_BUY_THRESHOLD,
    EVR_SELL_THRESHOLD,
    MIN_ORDER_USDT,
    SELL_PERCENT,
    SYMBOL,
)
from evr_bot.crypto_utils import decrypt
from evr_bot.evr_data import get_evr_index
from evr_bot.market_data import (
    create_exchange,
    get_balance,
    get_btc_price,
    get_last_db_date,
    get_ma600_from_db,
    get_reference_price_from_db,
    place_market_order,
)
from evr_bot.models import (
    BotStateEnum,
    ExecutionStatus,
    TradeAction,
    TradeLog,
    User,
    UserBotState,
)

logger = logging.getLogger("evr_bot.engine")


class TradingEngine:
    """Tek bir kullanici icin strateji motoru."""

    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.exchange = None
        self.state_obj: UserBotState | None = None

    def _init_exchange(self) -> None:
        api_key = decrypt(self.user.api_key_encrypted)
        api_secret = decrypt(self.user.api_secret_encrypted)
        self.exchange = create_exchange(api_key, api_secret)

    def _ensure_bot_state(self) -> None:
        self.state_obj = self.user.bot_state
        if not self.state_obj:
            self.state_obj = UserBotState(
                user_id=self.user.id,
                current_state=BotStateEnum.NORMAL,
            )
            self.db.add(self.state_obj)
            self.db.flush()

    def _log_trade(
        self,
        action: TradeAction,
        side: str | None = None,
        amount_btc: float | None = None,
        amount_usdt: float | None = None,
        price: float | None = None,
        order_id: str | None = None,
        client_order_id: str | None = None,
        evr_value: float | None = None,
        note: str | None = None,
        execution_status: ExecutionStatus = ExecutionStatus.UNKNOWN,
    ) -> TradeLog:
        log = TradeLog(
            user_id=self.user.id,
            action=action,
            side=side,
            amount_btc=amount_btc,
            amount_usdt=amount_usdt,
            price=price,
            order_id=order_id,
            client_order_id=client_order_id,
            evr_value=evr_value,
            bot_state_at=self.state_obj.current_state.value if self.state_obj else None,
            note=note,
            execution_status=execution_status,
        )
        self.db.add(log)
        return log

    @staticmethod
    def _total_kasa(usdt_balance: float, btc_balance: float, btc_price: float) -> float:
        return usdt_balance + (btc_balance * btc_price)

    def _change_state(self, new_state: BotStateEnum, note: str) -> None:
        old_state = self.state_obj.current_state
        self.state_obj.current_state = new_state
        logger.info("DURUM DEGISIKLIGI: %s -> %s | %s", old_state.name, new_state.name, note)
        self._log_trade(
            TradeAction.STATE_CHANGE,
            note=f"{old_state.name} -> {new_state.name}: {note}",
            execution_status=ExecutionStatus.FILLED,
        )

    def _build_client_order_id(self, label: str) -> str:
        ts = int(datetime.now(timezone.utc).timestamp())
        return f"evr{self.user.id}{label}{ts}{uuid4().hex[:6]}"[:36]

    @staticmethod
    def _extract_order_identifiers(order: dict) -> set[str]:
        info = order.get("info") or {}
        identifiers = set()
        candidates = [
            order.get("id"),
            order.get("clientOrderId"),
            order.get("client_order_id"),
            info.get("clientOrderId"),
            info.get("orderLinkId"),
            info.get("orderId"),
            info.get("order_id"),
        ]
        for candidate in candidates:
            if candidate:
                identifiers.add(str(candidate))
        return identifiers

    def _fetch_matching_order(self, client_order_id: str) -> dict | None:
        fetchers = (
            getattr(self.exchange, "fetch_orders", None),
            getattr(self.exchange, "fetch_closed_orders", None),
            getattr(self.exchange, "fetch_open_orders", None),
        )

        for fetcher in fetchers:
            if not callable(fetcher):
                continue

            try:
                orders = fetcher(SYMBOL, limit=500)
            except TypeError:
                try:
                    orders = fetcher(SYMBOL)
                except Exception as exc:
                    logger.warning("Order recovery fetch hatasi: %s", exc)
                    continue
            except Exception as exc:
                logger.warning("Order recovery fetch hatasi: %s", exc)
                continue

            for order in orders or []:
                if client_order_id in self._extract_order_identifiers(order):
                    return order

        return None

    def _recover_pending_trade(self, pending_log: TradeLog) -> bool:
        client_order_id = pending_log.client_order_id or pending_log.order_id
        if not client_order_id:
            logger.error(
                "PENDING log %s icin client order id yok. Manuel kontrol gerekli.",
                pending_log.id,
            )
            return False

        order = self._fetch_matching_order(client_order_id)
        if not order:
            from datetime import datetime, timezone
            
            # 24 saat timeout kontrolü
            if pending_log.timestamp:
                log_time = pending_log.timestamp
                if log_time.tzinfo is None:
                    log_time = log_time.replace(tzinfo=timezone.utc)
                    
                if (datetime.now(timezone.utc) - log_time).total_seconds() > 86400:
                    logger.error(
                        "PENDING log %s (CID: %s) 24 saatten eski ve bulunamadı. "
                        "Deadlock önlemek için UNKNOWN yapılıyor.",
                        pending_log.id, client_order_id
                    )
                    pending_log.execution_status = ExecutionStatus.UNKNOWN
                    pending_log.note = f"{(pending_log.note or '').strip()} [TIMEOUT 24H]".strip()
                    self.db.commit()
                    return True # True dönüyoruz ki bot kilitlenmesin

            logger.warning(
                "PENDING log %s icin borsada eslesen emir bulunamadi. Beklemede birakiliyor.",
                pending_log.id,
            )
            return False

        order_status = str(order.get("status") or "").lower()
        if order_status in {"closed", "filled"}:
            pending_log.amount_btc = order.get("filled", pending_log.amount_btc)
            pending_log.amount_usdt = order.get("cost", pending_log.amount_usdt)
            pending_log.price = order.get("average", pending_log.price)
            pending_log.order_id = str(order.get("id") or client_order_id)
            pending_log.execution_status = ExecutionStatus.FILLED
            pending_log.note = f"{(pending_log.note or '').strip()} [RECOVERED]".strip()

            if (
                pending_log.action == TradeAction.SHIELD_SELL
                and self.state_obj.current_state != BotStateEnum.SHIELD
            ):
                old_state = self.state_obj.current_state
                self.state_obj.current_state = BotStateEnum.SHIELD
                self._log_trade(
                    TradeAction.STATE_CHANGE,
                    note=f"{old_state.name} -> SHIELD: PENDING SHIELD emri recovery ile tamamlandi",
                    execution_status=ExecutionStatus.FILLED,
                )

            self.db.commit()
            logger.warning("PENDING log %s recovery ile FILLED yapildi.", pending_log.id)
            return True

        if order_status in {"canceled", "cancelled", "rejected", "expired"}:
            pending_log.execution_status = ExecutionStatus.FAILED
            pending_log.note = (
                f"{(pending_log.note or '').strip()} [RECOVERY FAILED:{order_status}]".strip()
            )
            self.db.commit()
            logger.warning("PENDING log %s recovery ile FAILED yapildi.", pending_log.id)
            return True

        logger.warning(
            "PENDING log %s borsada halen acik gorunuyor: %s",
            pending_log.id,
            order_status or "?",
        )
        return False

    def _recover_pending_trades(self) -> bool:
        pending_logs = (
            self.db.query(TradeLog)
            .filter(TradeLog.user_id == self.user.id)
            .filter(TradeLog.execution_status == ExecutionStatus.PENDING)
            .order_by(TradeLog.timestamp.asc())
            .all()
        )
        if not pending_logs:
            return True

        logger.warning(
            "User %s icin %d adet PENDING emir recovery kontrolune alindi.",
            self.user.email,
            len(pending_logs),
        )

        all_resolved = True
        for pending_log in pending_logs:
            try:
                recovered = self._recover_pending_trade(pending_log)
                all_resolved = all_resolved and recovered
            except Exception as exc:
                logger.exception("PENDING recovery hatasi (log=%s): %s", pending_log.id, exc)
                self.db.rollback()
                all_resolved = False

        return all_resolved

    def _execute_buy(self, usdt_amount: float, btc_price: float, evr: float) -> bool:
        amount_btc = usdt_amount / btc_price
        client_order_id = self._build_client_order_id("b")

        if usdt_amount < MIN_ORDER_USDT:
            logger.info(
                "Alim miktari minimum altinda: %.2f USDT < %.2f",
                usdt_amount,
                MIN_ORDER_USDT,
            )
            return False

        logger.info("ALIM: %.2f USDT -> ~%.8f BTC @ %.2f", usdt_amount, amount_btc, btc_price)

        pending_log = self._log_trade(
            TradeAction.BUY,
            side="buy",
            amount_btc=amount_btc,
            amount_usdt=usdt_amount,
            price=btc_price,
            order_id=None,
            client_order_id=client_order_id,
            evr_value=evr,
            note=f"EVR={evr:.1f} <= {EVR_BUY_THRESHOLD} | CID={client_order_id}",
            execution_status=ExecutionStatus.PENDING,
        )
        self.db.commit()

        try:
            order = place_market_order(
                self.exchange,
                "buy",
                amount_btc,
                client_order_id=client_order_id,
            )
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            # AG HATASI: Borsa emri almis olabilir, PENDING birakilir -> recovery akisi devralir.
            logger.exception("Alim ag hatasi: %s - Emir PENDING birakiliyor.", exc)
            pending_log.note = f"AG HATASI (PENDING): {str(exc)[:100]}..."
            self.db.commit()
            return False
        except Exception as exc:
            # YEREL HATA (ValueError, lot hatasi vb.): Borsaya emir gitmedi, guvenle FAILED.
            logger.exception("Alim yerel hatasi: %s - Emir FAILED.", exc)
            pending_log.execution_status = ExecutionStatus.FAILED
            pending_log.note = f"YEREL HATA: {str(exc)[:100]}..."
            self.db.commit()
            return False

        try:
            status = str(order.get("status") or "").lower()
            if status in ("canceled", "cancelled", "rejected", "expired"):
                logger.error("Alim emri borsa tarafindan reddedildi/iptal edildi: %s", status)
                pending_log.execution_status = ExecutionStatus.FAILED
                pending_log.note = f"BORSA REDDI: {status}"
                self.db.commit()
                return False

            if status not in ("closed", "filled"):
                # Emir henuz tamamlanmadi (open, partially_filled vb.) -> PENDING birak, recovery cozecek
                logger.warning("Alim emri final degil (status=%s). PENDING birakiliyor.", status)
                pending_log.order_id = str(order.get("id") or client_order_id)
                pending_log.note = f"BEKLEYEN EMIR (status={status}) | CID={client_order_id}"
                self.db.commit()
                return False

            pending_log.amount_btc = order.get("filled", amount_btc)
            pending_log.amount_usdt = order.get("cost", usdt_amount)
            pending_log.price = order.get("average", btc_price)
            pending_log.order_id = str(order.get("id") or client_order_id)
            pending_log.execution_status = ExecutionStatus.FILLED
            self.db.commit()
            return True
        except Exception as exc:
            self.db.rollback()
            logger.critical(
                "ALIM FILL COMMIT HATASI - Emir borsada gerceklesmis olabilir. "
                "Log PENDING recovery akisina birakildi. User=%s, Hata=%s",
                self.user.email,
                exc,
            )
            return False

    def _execute_sell(
        self,
        btc_amount: float,
        btc_price: float,
        evr: float,
        is_shield: bool = False,
    ) -> bool:
        usdt_value = btc_amount * btc_price
        client_order_id = self._build_client_order_id("h" if is_shield else "s")

        if usdt_value < MIN_ORDER_USDT:
            logger.info(
                "Satis miktari minimum altinda: %.2f USDT < %.2f",
                usdt_value,
                MIN_ORDER_USDT,
            )
            return False

        action = TradeAction.SHIELD_SELL if is_shield else TradeAction.SELL
        label = "KALKAN SATISI" if is_shield else "SATIM"
        logger.info("%s: %.8f BTC -> ~%.2f USDT @ %.2f", label, btc_amount, usdt_value, btc_price)

        pending_log = self._log_trade(
            action,
            side="sell",
            amount_btc=btc_amount,
            amount_usdt=usdt_value,
            price=btc_price,
            order_id=None,
            client_order_id=client_order_id,
            evr_value=evr,
            note=(
                f"KALKAN SATISI | CID={client_order_id}"
                if is_shield
                else f"EVR={evr:.1f} >= {EVR_SELL_THRESHOLD} | CID={client_order_id}"
            ),
            execution_status=ExecutionStatus.PENDING,
        )
        self.db.commit()

        try:
            order = place_market_order(
                self.exchange,
                "sell",
                btc_amount,
                client_order_id=client_order_id,
            )
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            # AG HATASI: Borsa emri almis olabilir, PENDING birakilir -> recovery akisi devralir.
            logger.exception("Satis ag hatasi: %s - Emir PENDING birakiliyor.", exc)
            pending_log.note = f"AG HATASI (PENDING): {str(exc)[:100]}..."
            self.db.commit()
            return False
        except Exception as exc:
            # YEREL HATA (ValueError, lot hatasi vb.): Borsaya emir gitmedi, guvenle FAILED.
            logger.exception("Satis yerel hatasi: %s - Emir FAILED.", exc)
            pending_log.execution_status = ExecutionStatus.FAILED
            pending_log.note = f"YEREL HATA: {str(exc)[:100]}..."
            self.db.commit()
            return False

        try:
            status = str(order.get("status") or "").lower()
            if status in ("canceled", "cancelled", "rejected", "expired"):
                logger.error("Satis emri borsa tarafindan reddedildi/iptal edildi: %s", status)
                pending_log.execution_status = ExecutionStatus.FAILED
                pending_log.note = f"BORSA REDDI: {status}"
                self.db.commit()
                return False

            if status not in ("closed", "filled"):
                # Emir henuz tamamlanmadi (open, partially_filled vb.) -> PENDING birak, recovery cozecek
                logger.warning("Satis emri final degil (status=%s). PENDING birakiliyor.", status)
                pending_log.order_id = str(order.get("id") or client_order_id)
                pending_log.note = f"BEKLEYEN EMIR (status={status}) | CID={client_order_id}"
                self.db.commit()
                return False

            pending_log.amount_btc = order.get("filled", btc_amount)
            pending_log.amount_usdt = order.get("cost", usdt_value)
            pending_log.price = order.get("average", btc_price)
            pending_log.order_id = str(order.get("id") or client_order_id)
            pending_log.execution_status = ExecutionStatus.FILLED

            if is_shield:
                old_state = self.state_obj.current_state
                self.state_obj.current_state = BotStateEnum.SHIELD
                self._log_trade(
                    TradeAction.STATE_CHANGE,
                    note=f"{old_state.name} -> SHIELD: KALKAN SATISI GERCEKLESTI",
                    execution_status=ExecutionStatus.FILLED,
                )

            self.db.commit()
            return True
        except Exception as exc:
            self.db.rollback()
            logger.critical(
                "SATIS FILL COMMIT HATASI - Emir borsada gerceklesmis olabilir. "
                "Log PENDING recovery akisina birakildi. User=%s, Hata=%s",
                self.user.email,
                exc,
            )
            return False

    def _apply_evr_rules(self, evr: float, btc_price: float, balances: dict) -> None:
        total = self._total_kasa(balances["usdt"], balances["btc"], btc_price)

        if evr <= EVR_BUY_THRESHOLD:
            buy_usdt = min(total * BUY_PERCENT, balances["usdt"])
            if buy_usdt >= MIN_ORDER_USDT:
                self._execute_buy(buy_usdt, btc_price, evr)
            else:
                logger.info(
                    "EVR=%.1f <= %.1f ama yetersiz USDT (%.2f)",
                    evr,
                    EVR_BUY_THRESHOLD,
                    balances["usdt"],
                )
            return

        if evr >= EVR_SELL_THRESHOLD:
            sell_btc = balances["btc"] * SELL_PERCENT
            if sell_btc * btc_price >= MIN_ORDER_USDT:
                self._execute_sell(sell_btc, btc_price, evr)
            else:
                logger.info(
                    "EVR=%.1f >= %.1f ama yetersiz BTC (%.8f)",
                    evr,
                    EVR_SELL_THRESHOLD,
                    balances["btc"],
                )
            return

        logger.info(
            "EVR=%.1f -> Notr bolge (%.1f < EVR < %.1f), islem yok.",
            evr,
            EVR_BUY_THRESHOLD,
            EVR_SELL_THRESHOLD,
        )

    def run_shield_check(self) -> dict:
        result = {
            "success": False,
            "user_id": self.user.id,
            "email": self.user.email,
            "job": "shield_check",
        }

        try:
            self._init_exchange()
            self._ensure_bot_state()

            if not self._recover_pending_trades():
                result["success"] = True
                result["action"] = "SKIP"
                result["warning"] = "Pending trade recovery tamamlanmadi; yeni shield cycle atlandi."
                return result

            btc_price, close_date = get_reference_price_from_db(self.db)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            if close_date != today_str:
                logger.warning(
                    "SHIELD FRESHNESS GUARD: Referans fiyat verisi bugune (%s) ait degil (Bulunan: %s).",
                    today_str,
                    close_date,
                )
                result["warning"] = f"Stale Data: Bugun={today_str}, DB={close_date}"
                result["success"] = True
                result["action"] = "SKIP"
                return result

            ma600 = get_ma600_from_db(self.db)
            balances = get_balance(self.exchange)

            self.state_obj.last_btc_price = btc_price
            self.state_obj.last_ma600 = ma600
            self.state_obj.last_run_at = datetime.now(timezone.utc)

            state = self.state_obj.current_state
            logger.info(
                "=== SHIELD CHECK === User=%s | Durum=%s | BTC=%.2f | MA600=%.2f",
                self.user.email,
                state.name,
                btc_price,
                ma600,
            )

            if state == BotStateEnum.NORMAL:
                if btc_price > (self.state_obj.eski_zirve_fiyati or 0.0):
                    self.state_obj.eski_zirve_fiyati = btc_price
                    logger.info("Yeni ATH: %.2f", btc_price)

                if btc_price < ma600:
                    self.state_obj.breakdown_reference_price = btc_price
                    if balances["btc"] * btc_price >= MIN_ORDER_USDT:
                        evr_val, _ = get_evr_index(self.db)
                        sell_ok = self._execute_sell(
                            balances["btc"],
                            btc_price,
                            evr_val,
                            is_shield=True,
                        )
                        if not sell_ok:
                            logger.critical("SHIELD SATISI BASARISIZ - state degistirilmedi.")
                            self._log_trade(
                                TradeAction.STATE_CHANGE,
                                note="SHIELD satisi basarisiz, state NORMAL kaldi.",
                                execution_status=ExecutionStatus.FAILED,
                            )
                    else:
                        logger.info("Shield: BTC bakiyesi yok veya minimum altinda.")
                        self._change_state(
                            BotStateEnum.SHIELD,
                            f"Fiyat ({btc_price:.2f}) < MA600 ({ma600:.2f}) (Bakiye Yok)",
                        )

            elif state == BotStateEnum.SHIELD:
                breakdown_ref = self.state_obj.breakdown_reference_price or 0.0
                drop_threshold = breakdown_ref * (1 - BREAKDOWN_DROP_PERCENT)

                if btc_price >= ma600:
                    self._change_state(
                        BotStateEnum.NORMAL,
                        f"Fiyat ({btc_price:.2f}) >= MA600 ({ma600:.2f}) -> RESET",
                    )
                elif breakdown_ref > 0 and btc_price <= drop_threshold:
                    self._change_state(
                        BotStateEnum.BLIND,
                        f"Fiyat ({btc_price:.2f}) <= %45 dusus ({drop_threshold:.2f})",
                    )

            elif state == BotStateEnum.BLIND:
                ath = self.state_obj.eski_zirve_fiyati or 0.0
                if ath > 0 and btc_price >= ath:
                    self._change_state(
                        BotStateEnum.NORMAL,
                        f"Fiyat ({btc_price:.2f}) >= ATH ({ath:.2f}) -> Kalkan yeniden kuruldu",
                    )

            self.db.commit()
            result["success"] = True
            result["state"] = self.state_obj.current_state.name
            result["btc_price"] = btc_price
            result["ma600"] = ma600
        except Exception as exc:
            logger.critical(
                "SHIELD DB COMMIT HATASI - Manuel kontrol gerekli. User=%s, Hata=%s",
                self.user.email,
                exc,
            )
            self.db.rollback()
            result["error"] = str(exc)

        return result

    def run_evr_cycle(self) -> dict:
        result = {
            "success": False,
            "user_id": self.user.id,
            "email": self.user.email,
            "job": "evr_cycle",
        }

        try:
            self._init_exchange()
            self._ensure_bot_state()

            if not self._recover_pending_trades():
                result["success"] = True
                result["action"] = "SKIP"
                result["warning"] = "Pending trade recovery tamamlanmadi; yeni EVR cycle atlandi."
                return result

            evr, evr_date = get_evr_index(self.db)
            if evr < 0:
                result["error"] = "EVR verisi alinamadi"
                logger.error("EVR verisi alinamadi - dongu iptal.")
                return result

            last_db_date = get_last_db_date(self.db)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            if last_db_date != today_str:
                logger.warning(
                    "FRESHNESS GUARD: SQL verisi bugune (%s) ait degil (Bulunan: %s).",
                    today_str,
                    last_db_date,
                )
                result["warning"] = f"Stale Data: Bugun={today_str}, DB={last_db_date}"
                result["success"] = True
                result["action"] = "SKIP"
                return result

            if evr_date and last_db_date and evr_date != last_db_date:
                # T-1 Tolerance: EVR'nin 1 gun gecikmeli (T-1) gelmesi normaldir. 
                # Eger fark 1 gunden fazlaysa iptal et.
                evr_dt = datetime.strptime(evr_date, "%Y-%m-%d").date()
                db_dt = datetime.strptime(last_db_date, "%Y-%m-%d").date()
                if (db_dt - evr_dt).days > 1:
                    result["warning"] = f"Tarih Uyumsuzlugu (>1 Gun): EVR={evr_date}, DB={last_db_date}"
                    logger.error("EVR tarihi DB tarihinden 1 gunden fazla eski. Islem iptal.")
                    result["success"] = True
                    result["action"] = "SKIP"
                    return result

            btc_price = get_btc_price(self.exchange)
            balances = get_balance(self.exchange)

            self.state_obj.last_evr_value = evr
            self.state_obj.last_btc_price = btc_price
            self.state_obj.last_run_at = datetime.now(timezone.utc)

            state = self.state_obj.current_state
            logger.info(
                "=== EVR CYCLE === User=%s | Durum=%s | EVR=%.1f | BTC=%.2f",
                self.user.email,
                state.name,
                evr,
                btc_price,
            )

            if state == BotStateEnum.NORMAL:
                self._apply_evr_rules(evr, btc_price, balances)
            elif state == BotStateEnum.SHIELD:
                if evr == 0.0:
                    self._change_state(BotStateEnum.BLIND, "EVR=0.0 -> Dip bolgesi")
                    balances = get_balance(self.exchange)
                    self._apply_evr_rules(evr, btc_price, balances)
                else:
                    logger.info("Shield aktif, EVR=%.1f. Islem yok.", evr)
            elif state == BotStateEnum.BLIND:
                logger.info("Blind mod aktif. EVR kurallari uygulaniyor.")
                self._apply_evr_rules(evr, btc_price, balances)

            self.db.commit()
            result["success"] = True
            result["state"] = self.state_obj.current_state.name
            result["evr"] = evr
            result["btc_price"] = btc_price
            result["action"] = "EXECUTED"
        except Exception as exc:
            logger.critical(
                "EVR DB COMMIT HATASI - Manuel kontrol gerekli. User=%s, Hata=%s",
                self.user.email,
                exc,
            )
            self.db.rollback()
            result["error"] = str(exc)

        return result

    def run_daily_cycle(self) -> dict:
        shield_result = self.run_shield_check()
        evr_result = self.run_evr_cycle()
        return {
            "success": shield_result.get("success", False) and evr_result.get("success", False),
            "user_id": self.user.id,
            "email": self.user.email,
            "state": evr_result.get("state", shield_result.get("state", "?")),
            "evr": evr_result.get("evr", 0),
            "btc_price": evr_result.get("btc_price", shield_result.get("btc_price", 0)),
            "ma600": shield_result.get("ma600", 0),
        }
